from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from healthcheck.analytics.coverage import (
    CoverageEvidence,
    CoverageObservation,
    CoverageService,
    calculate_coverage,
    resolve_coverage_status,
)
from healthcheck.canonical import (
    CanonicalCandidate,
    CanonicalSelectionResult,
    CanonicalSelectionService,
    select_canonical_candidates,
)
from healthcheck.config import Settings
from healthcheck.db.engine import (
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
    session_scope,
)
from healthcheck.db.models import CanonicalSelectionRun
from healthcheck.db.repositories import repositories_for
from healthcheck.runtime import prepare_runtime


@pytest.fixture
def database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            yield repositories_for(session), session
    finally:
        engine.dispose()


def test_pure_selection_is_reordered_deterministic_and_keeps_algorithm_groups_separate():
    xiaomi = CanonicalCandidate(
        metric_code="body_fat_pct",
        semantic_key="weigh-in-1",
        source_measurement_id="xiaomi-measurement",
        source_local_date=date(2026, 1, 1),
        compatibility_group="xiaomi-home-unknown",
        algorithm_code="xiaomi-home",
        algorithm_version="unknown",
    )
    openscale = CanonicalCandidate(
        metric_code="body_fat_pct",
        semantic_key="weigh-in-1",
        source_measurement_id="openscale-measurement",
        source_local_date=date(2026, 1, 1),
        compatibility_group="openscale-2",
        algorithm_code="openscale",
        algorithm_version="2",
    )

    with pytest.raises(ValueError, match="explicit compatibility_group"):
        select_canonical_candidates([xiaomi, openscale], metric_code="body_fat_pct")

    selected_forward = select_canonical_candidates(
        [xiaomi, openscale],
        metric_code="body_fat_pct",
        compatibility_group="xiaomi-home-unknown",
    )
    selected_reverse = select_canonical_candidates(
        [openscale, xiaomi],
        metric_code="body_fat_pct",
        compatibility_group="xiaomi-home-unknown",
    )
    assert selected_forward == selected_reverse == (xiaomi,)


def test_revision_recomputes_canonical_run_and_old_evidence_survives(database):
    repositories, session = database
    provider = repositories.providers.get_or_create("synthetic", "Synthetic", "scale")
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id, input_method="manual_import"
    )
    algorithm = repositories.measurement_algorithms.get_or_create(
        code="synthetic-weight",
        version="1",
        metric_family="weight",
        producer="healthcheck",
        compatibility_group="synthetic-weight-v1",
    )
    first_session = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        semantic_key="weigh-in-1",
        source_local_date=date(2026, 1, 1),
        temporal_precision="instant",
        source_timestamp_utc=datetime(2026, 1, 1, 8, tzinfo=UTC),
    )
    first_measurement = repositories.scalar_measurements.create(
        measurement_session_id=first_session.id,
        metric_code="weight",
        normalized_value=72.5,
        normalized_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )
    service = CanonicalSelectionService(session)
    first_result = service.select(scope_key="weight:2026-01", metric_code="weight")
    replay = service.select(scope_key="weight:2026-01", metric_code="weight")

    assert first_result.status == "succeeded"
    assert replay.replayed is True
    assert replay.id == first_result.id
    session.expire_all()
    reloaded_replay = CanonicalSelectionService(session).select(
        scope_key="weight:2026-01", metric_code="weight"
    )
    assert reloaded_replay.replayed is True
    assert reloaded_replay.id == first_result.id
    assert [item.source_measurement_id for item in first_result.selections] == [
        first_measurement.id
    ]

    revision_session = repositories.measurement_sessions.create_revision(
        first_session.id,
        source_local_date=date(2026, 1, 1),
        temporal_precision="instant",
        source_timestamp_utc=datetime(2026, 1, 1, 8, tzinfo=UTC),
    )
    revision = repositories.scalar_measurements.create_revision(
        first_measurement.id,
        measurement_session_id=revision_session.id,
        normalized_value=72.4,
        normalized_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )
    recomputed = service.recompute(scope_key="weight:2026-01", metric_code="weight")

    assert recomputed.id != first_result.id
    assert recomputed.run.supersedes_run_id == first_result.id
    assert [item.source_measurement_id for item in recomputed.selections] == [revision.id]
    old_value = session.get(type(first_measurement), first_measurement.id).normalized_value
    assert old_value == pytest.approx(72.5)
    assert repositories.scalar_measurements.current_heads("weight") == [revision]


def test_persisted_run_allows_multiple_metrics_for_one_semantic_weigh_in(database):
    repositories, session = database
    provider = repositories.providers.get_or_create("synthetic", "Synthetic", "scale")
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id, input_method="manual_import"
    )
    weight_algorithm = repositories.measurement_algorithms.get_or_create(
        code="synthetic-weight",
        version="1",
        metric_family="weight",
        producer="healthcheck",
        compatibility_group="synthetic-weight-v1",
    )
    composition_algorithm = repositories.measurement_algorithms.get_or_create(
        code="synthetic-body-composition",
        version="1",
        metric_family="body_composition",
        producer="healthcheck",
        compatibility_group="synthetic-body-v1",
    )
    measurement_session = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        semantic_key="weigh-in-1",
        source_local_date=date(2026, 1, 1),
        temporal_precision="date",
    )
    weight = repositories.scalar_measurements.create(
        measurement_session_id=measurement_session.id,
        metric_code="weight",
        normalized_value=72.5,
        normalized_unit="kg",
        measurement_algorithm_id=weight_algorithm.id,
    )
    body_fat = repositories.scalar_measurements.create(
        measurement_session_id=measurement_session.id,
        metric_code="body_fat_pct",
        normalized_value=20.0,
        normalized_unit="%",
        measurement_algorithm_id=composition_algorithm.id,
    )

    result = CanonicalSelectionService(session).select(
        scope_key="mixed-metrics:2026-01-01",
        compatibility_group="synthetic-body-v1",
    )

    assert result.status == "succeeded"
    assert {(selection.metric_code, selection.semantic_key) for selection in result.selections} == {
        ("weight", "weigh-in-1"),
        ("body_fat_pct", "weigh-in-1"),
    }
    assert (
        repositories.canonical_selections.get_by_key(
            result.id, "weight", "weigh-in-1"
        ).source_measurement_id
        == weight.id
    )
    assert (
        repositories.canonical_selections.get_by_key(
            result.id, "body_fat_pct", "weigh-in-1"
        ).source_measurement_id
        == body_fat.id
    )
    assert len(repositories.canonical_selections.for_run(result.id)) == 2


def test_coverage_uses_sparse_cadence_and_all_states_without_zero_fallback():
    start = date(2026, 1, 1)
    evidence = [
        CoverageEvidence(
            datetime(2026, 1, 2, tzinfo=UTC),
            datetime(2026, 1, 3, tzinfo=UTC),
            "confirmed_empty",
        ),
        CoverageEvidence(
            datetime(2026, 1, 3, tzinfo=UTC),
            datetime(2026, 1, 4, tzinfo=UTC),
            "unavailable",
        ),
        CoverageEvidence(
            datetime(2026, 1, 4, tzinfo=UTC),
            datetime(2026, 1, 5, tzinfo=UTC),
            "failed",
        ),
    ]
    summary = calculate_coverage(
        start,
        date(2026, 1, 5),
        observations=[CoverageObservation(start, source_id="synthetic")],
        coverage_intervals=evidence,
        cadence_days=1,
    )

    assert summary.expected_bins == (
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 4),
        date(2026, 1, 5),
    )
    assert summary.covered_bins == (date(2026, 1, 1),)
    assert [item.status for item in summary.bins] == [
        "present",
        "confirmed_empty",
        "unavailable",
        "failed",
        "unknown",
    ]
    assert summary.bins[-1].observed_count is None
    assert summary.status_counts == {
        "present": 1,
        "confirmed_empty": 1,
        "unavailable": 1,
        "failed": 1,
        "unknown": 1,
    }
    assert resolve_coverage_status(["failed", "confirmed_empty"]) == "confirmed_empty"
    assert resolve_coverage_status(["failed", "confirmed_empty", "unavailable"]) == "unavailable"
    earlier_empty = CoverageEvidence(
        datetime(2026, 1, 6, tzinfo=UTC),
        datetime(2026, 1, 7, tzinfo=UTC),
        "confirmed_empty",
        computed_at=datetime(2026, 1, 7, 8, tzinfo=UTC),
    )
    later_failure = CoverageEvidence(
        datetime(2026, 1, 6, tzinfo=UTC),
        datetime(2026, 1, 7, tzinfo=UTC),
        "failed",
        computed_at=datetime(2026, 1, 7, 9, tzinfo=UTC),
    )
    assert resolve_coverage_status([earlier_empty, later_failure]) == "failed"
    assert (
        resolve_coverage_status(
            [
                {
                    "status": "confirmed_empty",
                    "computed_at": "2026-01-07T08:00:00Z",
                    "interval_end": "2026-01-07T00:00:00Z",
                    "interval_id": "empty-map",
                },
                {
                    "status": "failed",
                    "computed_at": "2026-01-07T09:00:00Z",
                    "interval_end": "2026-01-07T00:00:00Z",
                    "interval_id": "failed-map",
                },
            ]
        )
        == "failed"
    )


def test_coverage_interval_reordering_has_stable_ids_and_tie_precedence():
    empty = CoverageEvidence(
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
        "confirmed_empty",
        interval_id="empty",
    )
    failure = CoverageEvidence(
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
        "failed",
        interval_id="failure",
    )

    forward = calculate_coverage(
        date(2026, 1, 1),
        date(2026, 1, 1),
        coverage_intervals=[failure, empty],
        cadence_days=1,
    )
    reverse = calculate_coverage(
        date(2026, 1, 1),
        date(2026, 1, 1),
        coverage_intervals=[empty, failure],
        cadence_days=1,
    )

    assert forward.as_dict() == reverse.as_dict()
    assert forward.bins[0].status == "confirmed_empty"
    assert forward.bins[0].interval_ids == ("empty", "failure")


def test_coverage_service_reads_persisted_utc_interval_and_current_heads(database):
    repositories, session = database
    provider = repositories.providers.get_or_create("synthetic", "Synthetic", "scale")
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id, input_method="manual_import"
    )
    algorithm = repositories.measurement_algorithms.get_or_create(
        code="synthetic-weight",
        version="1",
        metric_family="weight",
        producer="healthcheck",
        compatibility_group="synthetic-weight-v1",
    )
    measurement_session = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        semantic_key="weigh-in-1",
        source_local_date=date(2026, 1, 1),
        temporal_precision="date",
    )
    repositories.scalar_measurements.create(
        measurement_session_id=measurement_session.id,
        metric_code="weight",
        normalized_value=72.5,
        normalized_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )
    repositories.coverage.record(
        provider_id=provider.id,
        acquisition_source_id=source.id,
        stream_code="weight",
        metric_code="weight",
        interval_start=datetime(2026, 1, 2, tzinfo=UTC),
        interval_end=datetime(2026, 1, 3, tzinfo=UTC),
        resolution="day",
        status="confirmed_empty",
        calculation_rule_version="coverage-v1",
    )
    summary = CoverageService(session).summarize(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 7),
        provider_id=provider.id,
        acquisition_source_id=source.id,
    )

    assert summary.observed_dates == (date(2026, 1, 1),)
    assert summary.bins[0].status == "present"
    assert summary.bins[0].source_breakdown == {source.id: 1}
    assert summary.cadence_days == 7


def test_coverage_service_filters_observations_by_provider(database):
    repositories, session = database
    first_provider = repositories.providers.get_or_create("synthetic-a", "Synthetic A", "scale")
    second_provider = repositories.providers.get_or_create("synthetic-b", "Synthetic B", "scale")
    first_source = repositories.acquisition_sources.get_or_create(
        provider_id=first_provider.id, input_method="manual_import"
    )
    second_source = repositories.acquisition_sources.get_or_create(
        provider_id=second_provider.id, input_method="manual_import"
    )
    algorithm = repositories.measurement_algorithms.get_or_create(
        code="synthetic-weight",
        version="1",
        metric_family="weight",
        producer="healthcheck",
        compatibility_group="synthetic-weight-v1",
    )
    for source, semantic_key, value in (
        (first_source, "first", 72.5),
        (second_source, "second", 73.5),
    ):
        measurement_session = repositories.measurement_sessions.create_confirmed(
            acquisition_source_id=source.id,
            semantic_key=semantic_key,
            source_local_date=date(2026, 1, 1),
            temporal_precision="date",
        )
        repositories.scalar_measurements.create(
            measurement_session_id=measurement_session.id,
            metric_code="weight",
            normalized_value=value,
            normalized_unit="kg",
            measurement_algorithm_id=algorithm.id,
        )

    summary = CoverageService(session).summarize(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 7),
        provider_id=first_provider.id,
    )

    assert summary.observed_dates == (date(2026, 1, 1),)
    assert summary.source_breakdown == {first_source.id: 1}


def test_orm_candidate_excludes_a_superseded_measurement(database):
    repositories, session = database
    provider = repositories.providers.get_or_create("synthetic", "Synthetic", "scale")
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id, input_method="manual_import"
    )
    algorithm = repositories.measurement_algorithms.get_or_create(
        code="synthetic-weight",
        version="1",
        metric_family="weight",
        producer="healthcheck",
        compatibility_group="synthetic-weight-v1",
    )
    first_session = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        semantic_key="weigh-in-1",
        source_local_date=date(2026, 1, 1),
        temporal_precision="date",
    )
    first_measurement = repositories.scalar_measurements.create(
        measurement_session_id=first_session.id,
        metric_code="weight",
        normalized_value=72.5,
        normalized_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )
    revision_session = repositories.measurement_sessions.create_revision(
        first_session.id,
        source_local_date=date(2026, 1, 1),
        temporal_precision="date",
    )
    repositories.scalar_measurements.create_revision(
        first_measurement.id,
        measurement_session_id=revision_session.id,
        normalized_value=72.4,
        normalized_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )

    result = CanonicalSelectionService(session).select(
        scope_key="weight:stale-candidate",
        metric_code="weight",
        candidates=[first_measurement],
    )

    assert result.status == "succeeded"
    assert result.selections == ()
    assert result.exclusions[0].reason_code == "superseded"


def test_derived_selection_requires_current_inputs_and_requested_version(database):
    repositories, session = database
    provider = repositories.providers.get_or_create("synthetic", "Synthetic", "scale")
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id, input_method="manual_import"
    )
    algorithm = repositories.measurement_algorithms.get_or_create(
        code="synthetic-weight",
        version="1",
        metric_family="weight",
        producer="healthcheck",
        compatibility_group="synthetic-weight-v1",
    )
    measurement_session = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        semantic_key="weigh-in-1",
        source_local_date=date(2026, 1, 1),
        temporal_precision="date",
    )
    input_measurement = repositories.scalar_measurements.create(
        measurement_session_id=measurement_session.id,
        metric_code="weight",
        normalized_value=72.5,
        normalized_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )
    derived = repositories.derived_measurements.create(
        metric_code="fat_mass_kg",
        normalized_value=14.5,
        normalized_unit="kg",
        algorithm_code="body-composition-decomposition",
        algorithm_version="v1",
        parameters={"compatibility_group": "synthetic-body-v1"},
        input_measurement_ids=[input_measurement.id],
        source_session_id=measurement_session.id,
    )

    result = CanonicalSelectionService(session).select(
        scope_key="fat-mass:2026-01",
        metric_code="fat_mass_kg",
        compatibility_group="synthetic-body-v1",
    )
    assert [item.derived_measurement_id for item in result.selections] == [derived.id]

    revised_session = repositories.measurement_sessions.create_revision(
        measurement_session.id,
        source_local_date=date(2026, 1, 1),
        temporal_precision="date",
    )
    repositories.scalar_measurements.create_revision(
        input_measurement.id,
        measurement_session_id=revised_session.id,
        normalized_value=72.4,
        normalized_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )
    recomputed = CanonicalSelectionService(session).recompute(
        scope_key="fat-mass:2026-01",
        metric_code="fat_mass_kg",
        compatibility_group="synthetic-body-v1",
    )
    assert recomputed.id != result.id
    assert recomputed.run.supersedes_run_id == result.id
    assert recomputed.selections == ()


def test_invalid_selection_is_durable_through_session_scope(database):
    _repositories, session = database
    engine = session.get_bind()
    with session_scope(engine) as setup_session:
        setup_repositories = repositories_for(setup_session)
        provider = setup_repositories.providers.get_or_create(
            "synthetic-failure", "Synthetic Failure", "scale"
        )
        source = setup_repositories.acquisition_sources.get_or_create(
            provider_id=provider.id, input_method="manual_import"
        )
        algorithm = setup_repositories.measurement_algorithms.get_or_create(
            code="synthetic-failure-weight",
            version="1",
            metric_family="weight",
            producer="healthcheck",
            compatibility_group="synthetic-failure-v1",
        )
        measurement_session = setup_repositories.measurement_sessions.create_confirmed(
            acquisition_source_id=source.id,
            semantic_key="a-valid-weigh-in",
            source_local_date=date(2026, 1, 1),
            temporal_precision="date",
        )
        valid_measurement = setup_repositories.scalar_measurements.create(
            measurement_session_id=measurement_session.id,
            metric_code="weight",
            normalized_value=72.5,
            normalized_unit="kg",
            measurement_algorithm_id=algorithm.id,
        )

    with session_scope(engine) as scoped_session:
        result = CanonicalSelectionService(scoped_session).select(
            scope_key="invalid:scope",
            metric_code="weight",
            candidates=[
                CanonicalCandidate(
                    metric_code="weight",
                    semantic_key="a-valid-weigh-in",
                    source_measurement_id=valid_measurement.id,
                ),
                CanonicalCandidate(
                    metric_code="weight",
                    semantic_key="z-missing-weigh-in",
                    source_measurement_id="missing-source-measurement",
                ),
            ],
        )
        assert isinstance(result, CanonicalSelectionResult)
        assert result.status == "failed"
        assert result.failure_reason == "canonical_selection_reference_missing"
        assert result.selections == ()

    with create_session_factory(engine)() as fresh_session:
        failed = fresh_session.scalar(
            select(CanonicalSelectionRun).where(CanonicalSelectionRun.scope_key == "invalid:scope")
        )
        assert failed is not None
        assert failed.status == "failed"
        assert failed.failure_reason == "canonical_selection_reference_missing"
        assert (
            repositories_for(fresh_session).canonical_selection_runs.latest_successful(
                "invalid:scope"
            )
            is None
        )
        assert repositories_for(fresh_session).canonical_selections.for_run(failed.id) == []
