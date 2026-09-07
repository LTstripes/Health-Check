"""End-to-end regressions for bounded activity pagination; synthetic data only."""

from pathlib import Path

import pytest
from sqlalchemy import select

from healthcheck.config import Settings
from healthcheck.db.models import GarminPayloadObservation, SyncStreamState
from healthcheck.garmin.backfill import run_garmin_historical_backfill
from healthcheck.garmin.sync import ACTIVITY_PAGE_SIZE, GarminSyncStatus
from test_garmin_collection_reconciliation import (
    AS_OF,
    _activity,
    _activity_rows,
    _client,
    _engine_factory,
    _run,
)


@pytest.mark.parametrize("historical", [True, False], ids=["backfill", "incremental"])
@pytest.mark.parametrize("stop", ["budget", "page_cap"])
def test_activity_pagination_resumes_unread_page(tmp_path: Path, monkeypatch, historical, stop):
    offsets = []

    def pages(_path, **kwargs):
        offset = int(kwargs["params"]["start"])
        offsets.append(offset)
        if offset == 0:
            return [_activity(i + 1) for i in range(ACTIVITY_PAGE_SIZE)]
        return [_activity(9999)]

    client = _client()
    client.responses["connectapi"] = pages
    state_code = "garmin_historical:activities" if historical else "activities"

    def run(page_budget):
        if historical:
            return run_garmin_historical_backfill(
                Settings(data_dir=tmp_path / "runtime"),
                client=client,
                start=AS_OF,
                end=AS_OF,
                streams=["activities"],
                chunk_days=1,
                max_provider_requests=page_budget,
            )
        # Nine accepted per-day surfaces run before the activities surface.
        return _run(tmp_path, client, max_provider_requests=9 + page_budget)

    def snapshot():
        engine, factory = _engine_factory(tmp_path)
        try:
            with factory() as session:
                rows = _activity_rows(session)
                current = {
                    r.external_record_id: r.id for r in rows if r.projection_status == "current"
                }
                state = session.scalar(
                    select(SyncStreamState).where(SyncStreamState.stream_code == state_code)
                )
                success = (state.cursor, state.watermark, state.last_success_at)
                observations = {
                    r.id
                    for r in session.scalars(
                        select(GarminPayloadObservation).where(
                            GarminPayloadObservation.stream_code == "activity"
                        )
                    )
                }
                state_codes = set(session.scalars(select(SyncStreamState.stream_code)))
                return current, len(rows), success, observations, state_codes
        finally:
            engine.dispose()

    if stop == "page_cap":
        monkeypatch.setattr("healthcheck.garmin.sync.MAX_ACTIVITY_PAGES", 1)
    first = run(1 if stop == "budget" else 2)
    initial, count, success, observations, codes = snapshot()
    assert count == ACTIVITY_PAGE_SIZE
    assert len(observations) == 1  # partial raw observation is retained
    attempt = next(a for a in first.attempts if a.surface == "activities")
    assert attempt.status is GarminSyncStatus.PARTIAL
    assert first.status is GarminSyncStatus.PARTIAL
    assert attempt.coverage_status == "unknown"
    assert success == (None, None, None)
    assert (
        ("activities" not in codes) if historical else ("garmin_historical:activities" not in codes)
    )

    monkeypatch.setattr("healthcheck.garmin.sync.MAX_ACTIVITY_PAGES", 2)
    second = run(2)
    complete, count, success, later_observations, _ = snapshot()
    assert second.status is GarminSyncStatus.SUCCEEDED
    assert offsets == [0, 0, ACTIVITY_PAGE_SIZE]
    assert count == ACTIVITY_PAGE_SIZE + 1 and "9999" in complete
    assert all(complete[key] == value for key, value in initial.items())
    assert observations < later_observations
    assert success[0] == AS_OF.isoformat() and all(v is not None for v in success)

    third = run(2)
    replay, count, _, replay_observations, _ = snapshot()
    assert third.status is GarminSyncStatus.SUCCEEDED
    assert replay == complete and count == ACTIVITY_PAGE_SIZE + 1
    if historical:
        assert third.request_count == 0
        assert offsets == [0, 0, ACTIVITY_PAGE_SIZE]
        assert replay_observations == later_observations
    else:
        assert offsets == [0, 0, ACTIVITY_PAGE_SIZE, 0, ACTIVITY_PAGE_SIZE]
