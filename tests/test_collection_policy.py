"""Synthetic tests for the explicit collection-policy boundary (#238)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from healthcheck import cli
from healthcheck.collection_policy import (
    COLLECTION_POLICY_CONTRACT_VERSION,
    COLLECTION_POLICY_FILENAME,
    COLLECTION_POLICY_PROVENANCE,
    CollectionPolicyBusyError,
    CollectionPolicyResolution,
    CollectionPolicyRuntimeError,
    CollectionPolicyStatus,
    CollectionPolicyUpdateError,
    collection_policy_path,
    project_collection_policy_resolution,
    resolve_collection_policy,
    set_collection_policy,
)
from healthcheck.config import Settings
from healthcheck.db.engine import (
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
)
from healthcheck.db.models import (
    AcquisitionSource,
    Base,
    GoogleSource,
    GoogleSourceRecord,
    Provider,
    SyncStreamState,
)
from healthcheck.external_runtime_lock import ExternalRuntimeOperationLock
from healthcheck.owner_refresh import OwnerRefreshPolicyError, run_owner_refresh
from healthcheck.runtime import prepare_runtime, resolve_runtime_paths
from healthcheck.source_freshness import SCOPE_BY_KEY, Facts
from healthcheck.source_freshness_consumer import read_consumer_freshness_projection
from healthcheck.source_freshness_read import read_facts
from healthcheck.web.period_brief_query import PeriodBriefService
from healthcheck.web.source_freshness import router

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
DAY = date(2026, 10, 1)
OLD = NOW - timedelta(hours=100)


class _FakeGarminAuth:
    def __init__(self, settings, *, is_cn=False):
        pass

    def load_existing(self):
        return object(), SimpleNamespace()


class _FakeGarminSync:
    def __init__(self, settings, *, client, auth_result):
        pass

    def run(self, *, as_of, trailing_window_days):
        return SimpleNamespace(status="succeeded", as_of=as_of.isoformat())


class _FakeGarminTrainingSync:
    def __init__(self, settings, *, client, auth_result):
        pass

    def run(self, *, start, end):
        return {"status": "succeeded"}


def _fake_provider_patches(monkeypatch, owner_refresh, google_fn) -> None:
    monkeypatch.setattr(owner_refresh, "GarminAuthService", _FakeGarminAuth)
    monkeypatch.setattr(owner_refresh, "GarminIncrementalSync", _FakeGarminSync)
    monkeypatch.setattr(owner_refresh, "GarminTrainingSync", _FakeGarminTrainingSync)
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", lambda settings: object())
    monkeypatch.setattr(owner_refresh, "run_google_refresh", google_fn)


def _established_settings(tmp_path: Path) -> Settings:
    settings = Settings(data_dir=tmp_path / "runtime")
    migrate_database(prepare_runtime(settings))
    return settings


def _policy_file(settings: Settings) -> Path:
    return collection_policy_path(resolve_runtime_paths(settings))


def _write_raw_policy(settings: Settings, raw: str) -> Path:
    path = _policy_file(settings)
    path.write_text(raw, encoding="utf-8")
    return path


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": COLLECTION_POLICY_CONTRACT_VERSION,
        "provenance": COLLECTION_POLICY_PROVENANCE,
        "revision": 1,
        "updated_at_utc": "2026-10-01T18:20:00Z",
        "disabled_streams": ["google:heart_rate"],
    }
    payload.update(overrides)
    return payload


def _fresh_facts_for_other_scopes(scope_key: str) -> Facts:
    if scope_key == "google:heart_rate":
        return Facts(
            last_attempt_at_utc=OLD,
            last_success_at_utc=OLD,
            evidence_at_utc=OLD,
            observed_once=True,
        )
    if scope_key == "weight":
        return Facts(confirmed_weight=True, observed_once=True)
    if scope_key.startswith("garmin:activities"):
        return Facts(
            last_attempt_at_utc=NOW,
            last_success_at_utc=NOW,
            coverage="complete",
            activity_count=0,
        )
    return Facts(
        last_attempt_at_utc=NOW - timedelta(hours=1),
        last_success_at_utc=NOW - timedelta(hours=1),
        evidence_at_utc=NOW - timedelta(hours=1),
        observed_once=True,
    )


def _patch_freshness_facts(monkeypatch) -> None:
    import healthcheck.source_freshness_consumer as consumer_module

    def fake_read_facts(_session, scope, **kwargs):
        return _fresh_facts_for_other_scopes(scope.key)

    monkeypatch.setattr(consumer_module, "read_facts", fake_read_facts)


# --- policy schema / read / update / atomicity ---------------------------------


def test_absent_policy_is_not_an_off_switch(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    resolution = resolve_collection_policy(_policy_file(settings))
    assert resolution.status is CollectionPolicyStatus.ABSENT
    assert resolution.snapshot is None
    assert resolution.problem_code is None
    assert project_collection_policy_resolution(resolution) == {"status": "absent"}
    assert not _policy_file(settings).exists()


def test_supported_update_round_trip_cas_and_idempotent_noop(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    path = _policy_file(settings)

    first = set_collection_policy(settings, stream="google:heart_rate", state="off")
    assert (first.changed, first.previous_revision) == (True, None)
    assert first.policy.revision == 1
    assert first.policy.disabled_streams == ("google:heart_rate",)
    assert first.policy.provenance == "owner-explicit"
    assert len(first.policy.content_sha256) == 64
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document == {
        "contract_version": COLLECTION_POLICY_CONTRACT_VERSION,
        "provenance": COLLECTION_POLICY_PROVENANCE,
        "revision": 1,
        "updated_at_utc": first.policy.updated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "disabled_streams": ["google:heart_rate"],
    }

    noop = set_collection_policy(settings, stream="google:heart_rate", state="off")
    assert noop.changed is False
    assert noop.policy == first.policy

    enabled = set_collection_policy(
        settings, stream="google:heart_rate", state="on", expected_revision=1
    )
    assert (enabled.changed, enabled.policy.revision) == (True, 2)
    assert enabled.policy.disabled_streams == ()
    enabled_noop = set_collection_policy(
        settings, stream="google:heart_rate", state="on", expected_revision=2
    )
    assert enabled_noop.changed is False
    disabled_again = set_collection_policy(
        settings, stream="google:heart_rate", state="off", expected_revision=2
    )
    assert disabled_again.policy.revision == 3
    resolution = resolve_collection_policy(path)
    assert resolution.status is CollectionPolicyStatus.VALID
    assert resolution.snapshot == disabled_again.policy
    assert resolution.snapshot.content_sha256 == disabled_again.policy.content_sha256


def test_explicit_on_can_be_the_first_supported_write(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    update = set_collection_policy(settings, stream="google:heart_rate", state="on")
    assert (update.changed, update.previous_revision) == (True, None)
    assert update.policy.revision == 1
    assert update.policy.disabled_streams == ()
    resolution = resolve_collection_policy(_policy_file(settings))
    assert resolution.status is CollectionPolicyStatus.VALID
    assert resolution.snapshot.disabled_streams == ()


def test_expected_revision_conflict_leaves_policy_unchanged(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    path = _policy_file(settings)
    before = path.read_bytes()
    with pytest.raises(CollectionPolicyUpdateError) as exc_info:
        set_collection_policy(
            settings, stream="google:heart_rate", state="on", expected_revision=7
        )
    assert exc_info.value.error_code == "collection_policy_revision_conflict"
    assert path.read_bytes() == before
    assert resolve_collection_policy(path).snapshot.revision == 1

    absent_settings = _established_settings(tmp_path / "absent-runtime")
    with pytest.raises(CollectionPolicyUpdateError) as absent_info:
        set_collection_policy(
            absent_settings, stream="google:heart_rate", state="off", expected_revision=1
        )
    assert absent_info.value.error_code == "collection_policy_revision_conflict"
    assert not _policy_file(absent_settings).exists()


@pytest.mark.parametrize(
    ("raw", "problem_code"),
    [
        ("not json", "invalid_json"),
        ('{"contract_version": "a", "contract_version": "b"}', "invalid_json"),
        (json.dumps(_valid_payload(extra="field")), "invalid_shape"),
        (json.dumps([_valid_payload()]), "invalid_shape"),
        (json.dumps(_valid_payload(contract_version="healthcheck-collection-policy-v2")),
         "invalid_contract_version"),
        (json.dumps(_valid_payload(provenance="inferred")), "invalid_provenance"),
        (json.dumps(_valid_payload(revision=0)), "invalid_revision"),
        (json.dumps(_valid_payload(revision=True)), "invalid_revision"),
        (json.dumps(_valid_payload(updated_at_utc="2026-10-01T18:20:00+00:00")),
         "invalid_updated_at"),
        (json.dumps(_valid_payload(updated_at_utc="2026-02-30T18:20:00Z")),
         "invalid_updated_at"),
        (json.dumps(_valid_payload(disabled_streams=["garmin:sleep"])),
         "invalid_disabled_streams"),
        (json.dumps(_valid_payload(disabled_streams=["google:heart_rate", "google:heart_rate"])),
         "invalid_disabled_streams"),
        (json.dumps(_valid_payload(disabled_streams=["google:heart_rate", "garmin:sleep"])),
         "invalid_disabled_streams"),
    ],
)
def test_invalid_policy_is_typed_and_never_overwritten(
    tmp_path: Path, raw: str, problem_code: str
) -> None:
    settings = _established_settings(tmp_path)
    path = _write_raw_policy(settings, raw)
    resolution = resolve_collection_policy(path)
    assert resolution.status is CollectionPolicyStatus.INVALID
    assert resolution.problem_code == problem_code
    before = path.read_bytes()
    with pytest.raises(CollectionPolicyUpdateError) as exc_info:
        set_collection_policy(settings, stream="google:heart_rate", state="on")
    assert exc_info.value.error_code == "collection_policy_invalid"
    assert path.read_bytes() == before


def test_unreadable_policy_is_typed_and_never_overwritten(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    path = _policy_file(settings)
    path.mkdir()
    resolution = resolve_collection_policy(path)
    assert resolution.status is CollectionPolicyStatus.UNREADABLE
    assert resolution.problem_code == "read_error"
    with pytest.raises(CollectionPolicyUpdateError) as exc_info:
        set_collection_policy(settings, stream="google:heart_rate", state="off")
    assert exc_info.value.error_code == "collection_policy_unreadable"
    assert path.is_dir()


def test_oversize_policy_is_invalid(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    path = _write_raw_policy(settings, "{" + " " * (64 * 1024) + "}")
    resolution = resolve_collection_policy(path)
    assert resolution.status is CollectionPolicyStatus.INVALID
    assert resolution.problem_code == "oversize"


def test_valid_document_tolerates_formatting_and_key_order(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    path = _write_raw_policy(
        settings,
        '{\n  "disabled_streams": [],\n  "revision": 2,\n'
        '  "provenance": "owner-explicit",\n  "updated_at_utc": "2026-10-01T18:20:00Z",\n'
        '  "contract_version": "healthcheck-collection-policy-v1"\n}\n',
    )
    resolution = resolve_collection_policy(path)
    assert resolution.status is CollectionPolicyStatus.VALID
    assert resolution.snapshot.revision == 2
    assert resolution.snapshot.disabled_streams == ()


def test_update_requires_established_runtime(tmp_path: Path) -> None:
    missing = Settings(data_dir=tmp_path / "missing")
    with pytest.raises(CollectionPolicyRuntimeError) as missing_info:
        set_collection_policy(missing, stream="google:heart_rate", state="off")
    assert missing_info.value.error_code == "runtime_missing"
    assert not missing.data_dir.exists()

    unestablished = tmp_path / "unestablished"
    unestablished.mkdir()
    with pytest.raises(CollectionPolicyRuntimeError) as unestablished_info:
        set_collection_policy(
            Settings(data_dir=unestablished), stream="google:heart_rate", state="off"
        )
    assert unestablished_info.value.error_code == "runtime_not_established"
    assert not _policy_file(Settings(data_dir=unestablished)).exists()


def test_update_is_busy_while_another_operation_holds_the_lock(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    with ExternalRuntimeOperationLock(resolve_runtime_paths(settings), allow_reentrant=False):
        with pytest.raises(CollectionPolicyBusyError) as exc_info:
            set_collection_policy(settings, stream="google:heart_rate", state="off")
    assert exc_info.value.error_code == "collection_policy_busy"
    assert not _policy_file(settings).exists()


def test_update_rejects_unsupported_request_values(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    with pytest.raises(CollectionPolicyUpdateError) as stream_info:
        set_collection_policy(settings, stream="garmin:sleep", state="off")
    assert stream_info.value.error_code == "unsupported_policy_stream"
    with pytest.raises(CollectionPolicyUpdateError) as state_info:
        set_collection_policy(settings, stream="google:heart_rate", state="maybe")  # type: ignore[arg-type]
    assert state_info.value.error_code == "invalid_policy_state"
    with pytest.raises(CollectionPolicyUpdateError) as revision_info:
        set_collection_policy(
            settings, stream="google:heart_rate", state="off", expected_revision=0
        )
    assert revision_info.value.error_code == "invalid_expected_revision"
    assert not _policy_file(settings).exists()


def test_update_leaves_no_temporary_files_and_hash_is_deterministic(tmp_path: Path) -> None:
    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    root = resolve_runtime_paths(settings).root
    assert not list(root.glob(f".{COLLECTION_POLICY_FILENAME}.*.tmp"))
    path = _policy_file(settings)
    first = resolve_collection_policy(path)
    second = resolve_collection_policy(path)
    assert first == second
    assert project_collection_policy_resolution(first) == {
        "status": "valid",
        "contract_version": COLLECTION_POLICY_CONTRACT_VERSION,
        "revision": 1,
    }
    invalid = CollectionPolicyResolution(
        status=CollectionPolicyStatus.INVALID, problem_code="invalid_json"
    )
    assert project_collection_policy_resolution(invalid) == {
        "status": "invalid",
        "problem_code": "invalid_json",
    }


# --- freshness projection ------------------------------------------------------


def test_off_policy_keeps_history_but_removes_required_action(tmp_path, monkeypatch) -> None:
    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    resolution = resolve_collection_policy(_policy_file(settings))
    _patch_freshness_facts(monkeypatch)
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as session:
            core = read_consumer_freshness_projection(
                session,
                evaluated_at_utc=NOW,
                evaluation_local_date=DAY,
                collection_policy=resolution,
            )
    finally:
        engine.dispose()
    assert core["collection_policy"] == {
        "status": "valid",
        "contract_version": COLLECTION_POLICY_CONTRACT_VERSION,
        "revision": 1,
    }
    assert core["not_requested_required"] == [
        {
            "scope_key": "google:heart_rate",
            "state": "not_requested",
            "reason_code": "disabled",
        }
    ]
    assert core["owner"]["actionable_items"] == []
    assert core["owner"]["state"] == "fresh"
    assert core["providers"]["google"]["state"] == "fresh"
    serialized = json.dumps(core, sort_keys=True)
    assert OLD.isoformat() not in serialized
    assert "content_sha256" not in serialized
    assert "updated_at_utc" not in serialized
    assert "facts" not in serialized


def test_off_policy_keeps_real_chronology_in_local_core_details(tmp_path, monkeypatch) -> None:
    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    resolution = resolve_collection_policy(_policy_file(settings))
    _patch_freshness_facts(monkeypatch)
    import healthcheck.source_freshness_consumer as consumer_module

    engine = create_engine("sqlite://")
    try:
        with Session(engine) as session:
            core = consumer_module.evaluate_persisted_freshness(
                session,
                evaluated_at_utc=NOW,
                evaluation_local_date=DAY,
                collection_policy=resolution,
            )
    finally:
        engine.dispose()
    heart_rate = next(
        item for item in core["components"] if item["scope_key"] == "google:heart_rate"
    )
    assert (heart_rate["state"], heart_rate["reason_code"]) == ("not_requested", "disabled")
    facts = heart_rate["facts"]
    assert facts["disabled"] is True
    assert facts["last_successful_refresh_utc"] == OLD.isoformat()
    assert facts["latest_evidence_utc"] == OLD.isoformat()


@pytest.mark.parametrize("policy_kind", ["on", "absent", "invalid"])
def test_non_off_policy_keeps_stale_required_action(tmp_path, monkeypatch, policy_kind) -> None:
    settings = _established_settings(tmp_path)
    if policy_kind == "on":
        set_collection_policy(settings, stream="google:heart_rate", state="off")
        set_collection_policy(settings, stream="google:heart_rate", state="on")
        resolution = resolve_collection_policy(_policy_file(settings))
    elif policy_kind == "absent":
        resolution = resolve_collection_policy(_policy_file(settings))
    else:
        _write_raw_policy(settings, "{not json")
        resolution = resolve_collection_policy(_policy_file(settings))
    _patch_freshness_facts(monkeypatch)
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as session:
            core = read_consumer_freshness_projection(
                session,
                evaluated_at_utc=NOW,
                evaluation_local_date=DAY,
                collection_policy=resolution,
            )
    finally:
        engine.dispose()
    assert {
        "scope_key": "google:heart_rate",
        "state": "stale",
        "reason_code": "refresh_overdue",
    } in core["owner"]["actionable_items"]
    assert core["not_requested_required"] == []
    if policy_kind == "invalid":
        assert core["collection_policy"] == {
            "status": "invalid",
            "problem_code": "invalid_json",
        }


def test_enabled_sibling_failure_remains_visible_under_off_policy(tmp_path, monkeypatch) -> None:
    import healthcheck.source_freshness_consumer as consumer_module

    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    resolution = resolve_collection_policy(_policy_file(settings))

    def fake_read_facts(_session, scope, **kwargs):
        if scope.key == "google:sleep":
            return Facts(
                last_attempt_at_utc=OLD,
                last_success_at_utc=OLD,
                evidence_at_utc=OLD,
                observed_once=True,
            )
        return _fresh_facts_for_other_scopes(scope.key)

    monkeypatch.setattr(consumer_module, "read_facts", fake_read_facts)
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as session:
            core = read_consumer_freshness_projection(
                session,
                evaluated_at_utc=NOW,
                evaluation_local_date=DAY,
                collection_policy=resolution,
            )
    finally:
        engine.dispose()
    assert {
        "scope_key": "google:sleep",
        "state": "stale",
        "reason_code": "refresh_overdue",
    } in core["owner"]["actionable_items"]
    assert core["providers"]["google"]["state"] == "stale"


def test_disabled_and_unrequested_persisted_reads_preserve_history(tmp_path: Path) -> None:
    database = tmp_path / "facts.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    old_day = (NOW - timedelta(hours=100)).date()
    with Session(engine) as session:
        session.add(
            Provider(id="p", code="google_health", display_name="Google",
                     provider_kind="health_api")
        )
        session.add(AcquisitionSource(id="a", provider_id="p", input_method="provider_api"))
        session.add(
            GoogleSource(id="s", provider_id="p", acquisition_source_id="a",
                         source_kind="data_source", provider_code="google_health",
                         source_instance_id="synthetic", source_contract_version="synthetic")
        )
        session.add(
            SyncStreamState(id="state", provider_id="p",
                            stream_code="google:refresh:heart_rate:list:any",
                            last_attempt_at=OLD, last_success_at=OLD,
                            diagnostic_status="present")
        )
        session.add(
            GoogleSourceRecord(id="r", google_source_id="s", raw_payload_id="raw",
                               stream_code="heart_rate", query_mode="list",
                               record_identity_key="k", idempotency_key="i",
                               temporal_precision="date", source_local_date=old_day,
                               record_status="ok",
                               normalization_contract_version="synthetic")
        )
        session.commit()
    scope = SCOPE_BY_KEY["google:heart_rate"]
    with Session(engine) as session:
        disabled = read_facts(session, scope, evaluation_local_date=DAY, disabled=True)
        unrequested = read_facts(session, scope, evaluation_local_date=DAY, requested=False)
    engine.dispose()
    assert disabled.disabled is True
    assert disabled.last_success_at_utc == OLD
    assert disabled.evidence_local_date == old_day
    assert unrequested.requested is False
    assert unrequested.last_success_at_utc == OLD
    assert unrequested.evidence_local_date == old_day


# --- owner refresh -------------------------------------------------------------


def test_owner_refresh_bare_off_policy_excludes_heart_rate(tmp_path, monkeypatch) -> None:
    import healthcheck.owner_refresh as owner_refresh

    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    google_calls: list[dict] = []

    def fake_google(settings, **kwargs):
        google_calls.append(kwargs)
        return SimpleNamespace(status="succeeded")

    _fake_provider_patches(monkeypatch, owner_refresh, fake_google)
    report = run_owner_refresh(settings, as_of=DAY.isoformat(), trailing_window_days=7)
    normal_streams = google_calls[0]["streams"]
    assert "heart_rate" not in normal_streams
    assert len(normal_streams) == 8
    assert google_calls[1]["streams"] == ["sleep"]
    assert report.freshness["collection_policy"] == {
        "status": "valid",
        "contract_version": COLLECTION_POLICY_CONTRACT_VERSION,
        "revision": 1,
    }
    assert report.freshness["not_requested_required"] == [
        {
            "scope_key": "google:heart_rate",
            "state": "not_requested",
            "reason_code": "disabled",
        }
    ]


def test_owner_refresh_explicit_subset_under_off_is_allowed_and_unchanged(
    tmp_path, monkeypatch
) -> None:
    import healthcheck.owner_refresh as owner_refresh

    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    google_calls: list[dict] = []

    def fake_google(settings, **kwargs):
        google_calls.append(kwargs)
        return SimpleNamespace(status="succeeded")

    _fake_provider_patches(monkeypatch, owner_refresh, fake_google)
    run_owner_refresh(
        settings, as_of=DAY.isoformat(), trailing_window_days=7, streams=["sleep"]
    )
    assert google_calls[0]["streams"] == ["sleep"]
    resolution = resolve_collection_policy(_policy_file(settings))
    assert resolution.snapshot.revision == 1
    assert resolution.snapshot.disabled_streams == ("google:heart_rate",)


def test_owner_refresh_explicit_heart_rate_under_off_conflicts_before_providers(
    tmp_path, monkeypatch
) -> None:
    import healthcheck.owner_refresh as owner_refresh

    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")

    def forbidden(*args, **kwargs):
        pytest.fail("provider entrypoint called before the policy conflict")

    monkeypatch.setattr(owner_refresh, "GarminAuthService", forbidden)
    monkeypatch.setattr(owner_refresh, "GarminIncrementalSync", forbidden)
    monkeypatch.setattr(owner_refresh, "GarminTrainingSync", forbidden)
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", forbidden)
    monkeypatch.setattr(owner_refresh, "run_google_refresh", forbidden)
    with pytest.raises(OwnerRefreshPolicyError) as exc_info:
        run_owner_refresh(
            settings, as_of=DAY.isoformat(), trailing_window_days=7, streams=["heart_rate"]
        )
    assert exc_info.value.error_code == "collection_policy_conflict"


@pytest.mark.parametrize(
    ("raw", "error_code"),
    [("{not json", "collection_policy_invalid"), (None, "collection_policy_unreadable")],
)
def test_owner_refresh_ambiguous_policy_fails_before_providers(
    tmp_path, monkeypatch, raw, error_code
) -> None:
    import healthcheck.owner_refresh as owner_refresh

    settings = _established_settings(tmp_path)
    if raw is None:
        _policy_file(settings).mkdir()
    else:
        _write_raw_policy(settings, raw)

    def forbidden(*args, **kwargs):
        pytest.fail("provider entrypoint called with an ambiguous policy")

    monkeypatch.setattr(owner_refresh, "GarminAuthService", forbidden)
    monkeypatch.setattr(owner_refresh, "GarminIncrementalSync", forbidden)
    monkeypatch.setattr(owner_refresh, "GarminTrainingSync", forbidden)
    monkeypatch.setattr(owner_refresh, "GoogleAuthService", forbidden)
    monkeypatch.setattr(owner_refresh, "run_google_refresh", forbidden)
    with pytest.raises(OwnerRefreshPolicyError) as exc_info:
        run_owner_refresh(settings, as_of=DAY.isoformat(), trailing_window_days=7)
    assert exc_info.value.error_code == error_code


def test_owner_refresh_on_policy_restores_normal_freshness_checks(tmp_path, monkeypatch) -> None:
    import healthcheck.owner_refresh as owner_refresh

    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    set_collection_policy(settings, stream="google:heart_rate", state="on")

    def fake_google(settings, **kwargs):
        return SimpleNamespace(status="succeeded")

    _fake_provider_patches(monkeypatch, owner_refresh, fake_google)
    report = run_owner_refresh(
        settings, as_of=DAY.isoformat(), trailing_window_days=7, streams=["sleep"]
    )
    assert report.freshness["collection_policy"] == {
        "status": "valid",
        "contract_version": COLLECTION_POLICY_CONTRACT_VERSION,
        "revision": 2,
    }
    assert report.freshness["not_requested_required"] == []
    assert {
        "scope_key": "google:heart_rate",
        "state": "unknown",
        "reason_code": "never_observed",
    } in report.freshness["owner"]["actionable_items"]


# --- shared consumers / diagnostics --------------------------------------------


def test_owner_refresh_and_period_brief_share_persisted_policy(tmp_path, monkeypatch) -> None:
    import healthcheck.owner_refresh as owner_refresh
    import healthcheck.web.period_brief_query as period_brief_query

    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    fixed_now = datetime(2099, 1, 15, 12, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(owner_refresh, "datetime", FrozenDateTime)
    monkeypatch.setattr(period_brief_query, "datetime", FrozenDateTime)

    def fake_google(settings, **kwargs):
        return SimpleNamespace(status="succeeded")

    _fake_provider_patches(monkeypatch, owner_refresh, fake_google)
    report = run_owner_refresh(
        settings, as_of="2099-01-15", trailing_window_days=7
    )
    engine = create_sqlite_engine(resolve_runtime_paths(settings))
    try:
        with create_session_factory(engine)() as session:
            packet = PeriodBriefService(session, settings).build(
                start_date=date(2099, 1, 15), end_date=date(2099, 1, 15)
            )
    finally:
        engine.dispose()
    brief = packet["sections"]["data_quality"]["coverage"]["freshness"]
    assert report.freshness == brief
    assert brief["collection_policy"]["revision"] == 1
    assert brief["not_requested_required"] == [
        {
            "scope_key": "google:heart_rate",
            "state": "not_requested",
            "reason_code": "disabled",
        }
    ]


def test_period_brief_packet_identity_follows_policy_revision(tmp_path) -> None:
    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    engine = create_sqlite_engine(resolve_runtime_paths(settings))
    try:
        with create_session_factory(engine)() as session:
            first = PeriodBriefService(session, settings).build(
                start_date=DAY, end_date=DAY
            )
            repeated = PeriodBriefService(session, settings).build(
                start_date=DAY, end_date=DAY
            )
        set_collection_policy(settings, stream="google:heart_rate", state="on")
        with create_session_factory(engine)() as session:
            second = PeriodBriefService(session, settings).build(
                start_date=DAY, end_date=DAY
            )
    finally:
        engine.dispose()
    assert first["result_hash"] == repeated["result_hash"]
    assert first["result_hash"] != second["result_hash"]


def test_diagnostics_union_policy_and_request_facts(tmp_path) -> None:
    settings = _established_settings(tmp_path)
    set_collection_policy(settings, stream="google:heart_rate", state="off")
    paths = resolve_runtime_paths(settings)
    before = paths.database.read_bytes()
    app = FastAPI()
    app.state.runtime_paths = paths
    app.state.settings = SimpleNamespace(weight_cadence_days=7)
    app.include_router(router)
    client = TestClient(app)

    response = client.get(
        "/api/source-freshness",
        params={
            "evaluated_at_utc": NOW.isoformat(),
            "evaluation_local_date": DAY.isoformat(),
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["collection_policy"] == {
        "status": "valid",
        "contract_version": COLLECTION_POLICY_CONTRACT_VERSION,
        "revision": 1,
    }
    heart_rate = next(
        item for item in payload["components"] if item["scope_key"] == "google:heart_rate"
    )
    assert (heart_rate["state"], heart_rate["reason_code"]) == ("not_requested", "disabled")

    response = client.get(
        "/api/source-freshness",
        params={
            "evaluated_at_utc": NOW.isoformat(),
            "evaluation_local_date": DAY.isoformat(),
            "not_requested": ["google:heart_rate"],
            "disabled": ["garmin:sleep"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    heart_rate = next(
        item for item in payload["components"] if item["scope_key"] == "google:heart_rate"
    )
    assert (heart_rate["state"], heart_rate["reason_code"]) == ("not_requested", "disabled")
    garmin_sleep = next(
        item for item in payload["components"] if item["scope_key"] == "garmin:sleep"
    )
    assert garmin_sleep["state"] == "not_requested"
    assert paths.database.read_bytes() == before


def test_read_side_evaluation_never_writes_policy_or_config(tmp_path, monkeypatch) -> None:
    settings = _established_settings(tmp_path)
    root = resolve_runtime_paths(settings).root
    config_before = (root / "config.toml").read_bytes()
    _patch_freshness_facts(monkeypatch)
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as session:
            read_consumer_freshness_projection(
                session, evaluated_at_utc=NOW, evaluation_local_date=DAY
            )
    finally:
        engine.dispose()
    assert (root / "config.toml").read_bytes() == config_before
    assert not (root / COLLECTION_POLICY_FILENAME).exists()
    assert not list(root.glob(f".{COLLECTION_POLICY_FILENAME}.*.tmp"))


def test_cli_policy_read_and_set_round_trip(tmp_path, capsys) -> None:
    settings = _established_settings(tmp_path)
    root = str(resolve_runtime_paths(settings).root)

    code = cli.main(
        ["collection-policy-set", "--data-dir", root,
         "--stream", "google:heart_rate", "--state", "off"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["changed"] is True
    assert payload["policy"]["disabled_streams"] == ["google:heart_rate"]
    assert payload["privacy"]["health_timestamps_emitted"] is False

    code = cli.main(["collection-policy", "--data-dir", root])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "valid"
    assert payload["policy"]["revision"] == 1

    code = cli.main(
        ["collection-policy-set", "--data-dir", root,
         "--stream", "google:heart_rate", "--state", "on", "--expect-revision", "7"]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["error_code"] == "collection_policy_revision_conflict"

    code = cli.main(["collection-policy", "--data-dir", str(tmp_path / "missing")])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["error_code"] == "runtime_missing"

    code = cli.main(
        ["collection-policy-set", "--data-dir", root,
         "--stream", "garmin:sleep", "--state", "off"]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["error_code"] == "unsupported_policy_stream"
