"""Synthetic HRV calendar/identity recovery; no Owner profile or provider access."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from fixture_database import copy_migrated_database
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine
from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRawPayload,
    GarminRecordMetric,
    GarminSourceRecord,
    SyncStreamState,
)
from healthcheck.garmin import reprocess
from healthcheck.garmin.normalization import (
    HRV_CALENDAR_CONTRACT_VERSION,
    NORMALIZATION_CONTRACT_VERSION,
    GarminSourceIdentity,
    GarminTemporalDTO,
    normalize_garmin_payload,
    stable_garmin_reconciliation_key,
)
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.reprocess import run_garmin_reprocess
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.sync import PRODUCTION_SYNC_SURFACES, _collection_scope
from healthcheck.garmin.sync import _prepare_normalization_result as prepare
from healthcheck.runtime import prepare_runtime

DAY = date(2099, 1, 2)
RECEIPT = datetime(2099, 2, 1, tzinfo=UTC)
SURFACE = next(s for s in PRODUCTION_SYNC_SURFACES if s.code == "hrv_status")


def identity(name="one"):
    return GarminSourceIdentity(
        source_kind="provider",
        provider_code="garmin_connect",
        device_attributed=False,
        source_instance_id=f"garmin:synthetic-hrv:{name}",
    )


def payload(day=DAY, value=31):
    return {"hrvSummary": {"calendarDate": day.isoformat(), "weeklyAvg": value}}


def normalize(body, source=None):
    return normalize_garmin_payload(
        body, stream="daily_health", source_identity=source or identity()
    )


@pytest.fixture
def saved(tmp_path, request, tmp_path_factory):
    settings = Settings(data_dir=tmp_path / "synthetic-runtime")
    paths = prepare_runtime(settings)
    copy_migrated_database(paths, request, tmp_path_factory)
    engine = create_sqlite_engine(paths)
    factory = create_session_factory(engine)
    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    yield settings, factory, store
    engine.dispose()


def persist(
    saved,
    day=DAY,
    value=31,
    *,
    at=RECEIPT,
    legacy=False,
    source=None,
    body=None,
    encoded=None,
    window_start=None,
):
    _, factory, store = saved
    source = source or identity()
    body = payload(day, value) if body is None else body
    result = normalize(body, source)
    if legacy:
        # Reproduce the pinned v2 unknown-time reconciliation, including its shared key.
        records = tuple(
            replace(
                row,
                temporal=GarminTemporalDTO(precision="unknown"),
                sample_token=None,
                idempotency_key=stable_garmin_reconciliation_key(
                    source,
                    "daily_health",
                    surface="hrv_status",
                    temporal=GarminTemporalDTO(precision="unknown"),
                ),
            )
            for row in result.records
        )
        result = replace(result, records=records, contract_version=NORMALIZATION_CONTRACT_VERSION)
    else:
        result = prepare(SURFACE, body, result, day=day)
    with factory() as session:
        outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
            result,
            payload=body if encoded is None else encoded,
            source_identity=source,
            stream_code="daily_health",
            received_at=at,
            source_filename="hrv_status.json",
            source_window_start_utc=datetime.combine(window_start or day, datetime.min.time(), UTC),
            source_window_end_utc=datetime.combine(
                day + timedelta(days=1), datetime.min.time(), UTC
            ),
            collection_scope=_collection_scope(
                SURFACE,
                day=day,
                window_start=day,
                window_end=day,
                fetch_complete=True,
                coverage_status="present" if result.records else "unknown",
            ),
        )
        ids = outcome.source.id, outcome.raw_payload.id, outcome.observation.id
        session.commit()
        return ids


def projection(saved):
    with saved[1]() as session:
        return [
            (r.garmin_source_id, r.source_local_date, m.state, m.value_number)
            for r, m in session.execute(
                select(GarminSourceRecord, GarminRecordMetric)
                .join(
                    GarminRecordMetric,
                    GarminRecordMetric.record_id == GarminSourceRecord.id,
                )
                .where(
                    GarminSourceRecord.surface_code == "hrv_status",
                    GarminSourceRecord.projection_status == "current",
                    GarminRecordMetric.metric_code == "hrv_weekly_average_ms",
                )
            )
        ]


def originals(saved):
    with saved[1]() as session:
        return {
            model.__tablename__: {
                row.id: tuple(getattr(row, col.name) for col in model.__table__.columns)
                for row in session.scalars(select(model))
            }
            for model in (GarminRawPayload, GarminPayloadObservation, SyncStreamState)
        }


def test_nested_day_keeps_exact_provenance_without_sleep_clock():
    body = payload()
    body.update(startTimestampGMT="2099-01-01T20:00:00Z", startTimeGMT="2098-12-31T20:00:00Z")
    result = normalize(body)
    row = result.records[0]
    assert result.contract_version == HRV_CALENDAR_CONTRACT_VERSION
    assert row.temporal.precision.value == "date"
    assert row.temporal.local_date == DAY
    assert row.temporal.source_field == "payload.hrvSummary.calendarDate"
    assert row.temporal.source_local_field == "payload.hrvSummary.calendarDate"
    assert row.temporal.measured_at_utc is None
    assert row.temporal.source_timezone is None
    assert row.temporal.source_utc_offset_minutes is None
    assert row.metric("hrv_weekly_average_ms").field_path == "payload.hrvSummary.weeklyAvg"


@pytest.mark.parametrize(
    "bad", [None, "", "2099-02-30", " 2099-01-02", "2099-01-02T00:00:00Z", 0, True, {}, []]
)
def test_invalid_present_hrv_day_never_falls_back(bad):
    body = payload()
    body["hrvSummary"]["calendarDate"] = bad
    body["calendarDate"] = DAY.isoformat()
    result = normalize(body)
    assert result.records[0].temporal.local_date is None
    assert any(d.code == "hrv_calendar_date_invalid" for d in result.diagnostics)
    assert not prepare(SURFACE, body, result, day=DAY).records


@pytest.mark.parametrize("root", ["calendarDate", "date"])
def test_conflicting_calendar_dates_are_not_a_priority_choice(root):
    body = dict(payload(), **{root: (DAY + timedelta(days=1)).isoformat()})
    result = normalize(body)
    assert result.records[0].temporal.local_date is None
    assert any(d.code == "hrv_calendar_date_conflict" for d in result.diagnostics)
    assert not prepare(SURFACE, body, result, day=DAY).records


def test_missing_calendar_cannot_use_request_receipt_or_start_clock():
    body = {"hrvSummary": {"weeklyAvg": 31}, "startTimeGMT": "2099-01-02T00:00:00Z"}
    result = normalize(body)
    assert result.records[0].temporal.local_date is None
    assert not prepare(SURFACE, body, result, day=DAY).records


@pytest.mark.parametrize(
    "value,state",
    [(None, "null"), (0, "value"), (31, "value"), (True, "invalid"), ("31", "invalid")],
)
def test_weekly_presence_states_are_not_reinterpreted(value, state):
    row = normalize(payload(value=value)).records[0]
    assert row.metric("hrv_weekly_average_ms").state.value == state
    body = payload()
    del body["hrvSummary"]["weeklyAvg"]
    assert normalize(body).records[0].metric("hrv_weekly_average_ms").state.value == "missing"


def test_production_identity_separates_days_sources_and_value_corrections():
    def key(day, value, source):
        body = payload(day, value)
        return prepare(SURFACE, body, normalize(body, source), day=day).records[0].idempotency_key

    assert key(DAY, 31, identity()) == key(DAY, 72, identity())
    assert key(DAY, 31, identity()) != key(DAY + timedelta(days=1), 31, identity())
    assert key(DAY, 31, identity()) != key(DAY, 31, identity("two"))
    other = normalize_garmin_payload(
        {"calendarDate": DAY.isoformat(), "restingHeartRate": 50},
        stream="daily_health",
        source_identity=identity(),
    )
    assert other.contract_version == NORMALIZATION_CONTRACT_VERSION


def test_legacy_days_restore_without_loss_and_exact_replay_converges(saved, monkeypatch):
    def forbidden_fetch(*args, **kwargs):
        pytest.fail("offline HRV reprocess attempted provider/session access")

    monkeypatch.setattr("healthcheck.garmin.auth.GarminAuthService.load_existing", forbidden_fetch)
    for n in range(3):
        persist(saved, DAY + timedelta(days=n), at=RECEIPT + timedelta(hours=n), legacy=True)
    assert len(projection(saved)) == 1 and projection(saved)[0][1] is None
    before = originals(saved)
    files = {p: p.read_bytes() for p in saved[2].artifacts_root.rglob("*.json")}
    planned = run_garmin_reprocess(
        saved[0], start=DAY, end=DAY + timedelta(days=2), streams=["hrv_status"], dry_run=True
    )
    assert planned.processed_count == 0 and originals(saved) == before
    report = run_garmin_reprocess(
        saved[0], start=DAY, end=DAY + timedelta(days=2), streams=["hrv_status"]
    )
    assert report.processed_count == 3
    assert [r[1] for r in sorted(projection(saved), key=lambda r: r[1])] == [
        DAY + timedelta(days=n) for n in range(3)
    ]
    assert all(r[3] == 31 for r in projection(saved))
    after = originals(saved)
    for table, rows in before.items():
        assert all(after[table][key] == value for key, value in rows.items())
    assert after["sync_stream_state"] == before["sync_stream_state"]
    assert all(p.read_bytes() == value for p, value in files.items())
    with saved[1]() as session:
        retired = list(
            session.scalars(
                select(GarminSourceRecord).where(
                    GarminSourceRecord.projection_status == "retired",
                )
            )
        )
        assert len(retired) == 1
        assert retired[0].retire_reason == "hrv_calendar_identity_superseded_v3"
    second = run_garmin_reprocess(
        saved[0], start=DAY, end=DAY + timedelta(days=2), streams=["hrv_status"]
    )
    assert second.processed_count == 0 and originals(saved) == after


def test_bounded_restore_preserves_later_undated_row_and_other_source(saved):
    first_source = persist(saved, legacy=True)[0]
    persist(saved, DAY + timedelta(days=1), value=41, at=RECEIPT + timedelta(hours=1), legacy=True)
    persist(saved, value=61, legacy=True, source=identity("two"))
    report = run_garmin_reprocess(
        saved[0], start=DAY, end=DAY, streams=["hrv_status"], max_observations=1
    )
    assert report.remaining_observation_count == 1
    run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"], max_observations=1)
    rows = projection(saved)
    assert (first_source, None, "value", 41) in rows
    assert (first_source, DAY, "value", 31) in rows
    run_garmin_reprocess(
        saved[0], start=DAY + timedelta(days=1), end=DAY + timedelta(days=1), streams=["hrv_status"]
    )
    assert all(r[1] is not None for r in projection(saved))
    assert len(projection(saved)) == 3


def test_latest_day_correction_survives_stale_replay(saved):
    persist(saved, legacy=True)
    persist(saved, value=43, legacy=True, at=RECEIPT + timedelta(hours=1))
    run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    assert projection(saved)[0][3] == 43
    persist(saved, value=21, at=RECEIPT - timedelta(hours=1))
    assert projection(saved)[0][3] == 43


def test_new_dated_sync_does_not_hide_pending_legacy_transition(saved):
    persist(saved, legacy=True)
    persist(saved, value=43, at=RECEIPT + timedelta(hours=1))
    assert len(projection(saved)) == 2
    report = run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    assert report.processed_count == 1
    assert len(projection(saved)) == 1 and projection(saved)[0][3] == 43
    assert (
        run_garmin_reprocess(
            saved[0],
            start=DAY,
            end=DAY,
            streams=["hrv_status"],
        ).processed_count
        == 0
    )


def test_older_overlapping_window_cannot_restore_a_stale_legacy_day(saved):
    # Same returned day, two acquisition-window identities. A cap must not
    # expose the older value before the newer legacy day can be recovered.
    persist(saved, value=21, legacy=True, window_start=DAY - timedelta(days=1))
    persist(saved, value=43, legacy=True, at=RECEIPT + timedelta(hours=1))
    report = run_garmin_reprocess(
        saved[0],
        start=DAY,
        end=DAY,
        streams=["hrv_status"],
        max_observations=1,
    )
    assert report.remaining_observation_count == 0
    assert projection(saved)[0][3] == 43
    assert projection(saved)[0][1] == DAY
    assert len(projection(saved)) == 1


def apply_stored(saved, start, end, *, cap=1, dry_run=False):
    return reprocess.GarminCollectionReprocessor(saved[0])._run(
        saved[1],
        saved[2],
        start=start,
        end=end,
        surfaces=(SURFACE,),
        dry_run=dry_run,
        cap=cap,
    )


def overlapping_different_days(saved):
    later_day = DAY + timedelta(days=1)
    # The first acquisition spans both days but returns only DAY. The
    # collapsed legacy identity subsequently points at the later day's bytes.
    persist(
        saved,
        later_day,
        body=payload(DAY, 21),
        legacy=True,
        window_start=DAY,
        at=RECEIPT,
    )
    persist(saved, later_day, value=43, legacy=True, at=RECEIPT + timedelta(hours=1))
    return later_day


def assert_originals_preserved(saved, before):
    after = originals(saved)
    for table, rows in before.items():
        assert all(after[table][key] == value for key, value in rows.items())


def test_bounded_resume_advances_between_different_returned_days(saved):
    later_day = overlapping_different_days(saved)
    before = originals(saved)
    first = apply_stored(saved, DAY, later_day)
    assert first.processed_count == 1 and first.remaining_observation_count == 1
    assert {(r[1], r[3]) for r in projection(saved)} == {(DAY, 21), (None, 43)}
    after_first = originals(saved)
    # The pending legacy day must not make the already restored DAY consume
    # the next cap. Dry-run and apply must agree about the remaining work.
    planned = apply_stored(saved, DAY, later_day, dry_run=True)
    assert planned.remaining_observation_count == 0
    assert originals(saved) == after_first
    second = apply_stored(saved, DAY, later_day)
    assert second.processed_count == 1 and second.remaining_observation_count == 0
    assert {(r[1], r[3]) for r in projection(saved)} == {(DAY, 21), (later_day, 43)}
    converged = originals(saved)
    third = apply_stored(saved, DAY, later_day)
    assert third.processed_count == 0 and third.remaining_observation_count == 0
    assert originals(saved) == converged
    assert_originals_preserved(saved, before)


@pytest.mark.parametrize("first_day", [DAY, DAY + timedelta(days=1)])
def test_expanded_range_recovers_each_originals_own_day(saved, first_day):
    later_day = overlapping_different_days(saved)
    before = originals(saved)
    first = apply_stored(saved, first_day, first_day, cap=10)
    assert first.remaining_observation_count == 0
    expected = {(DAY, 21), (None, 43)} if first_day == DAY else {(later_day, 43)}
    assert {(r[1], r[3]) for r in projection(saved)} == expected
    # A newer current row for another day, or an earlier clipped attempt,
    # cannot stand in for the missing returned day when the range expands.
    expanded = apply_stored(saved, DAY, later_day, cap=10)
    assert expanded.processed_count == 1 and expanded.remaining_observation_count == 0
    assert {(r[1], r[3]) for r in projection(saved)} == {(DAY, 21), (later_day, 43)}
    assert apply_stored(saved, DAY, later_day, cap=10).processed_count == 0
    assert_originals_preserved(saved, before)


def legacy_projection(saved, source_id):
    with saved[1]() as session:
        row = session.scalars(
            select(GarminSourceRecord).where(
                GarminSourceRecord.garmin_source_id == source_id,
                GarminSourceRecord.surface_code == "hrv_status",
                GarminSourceRecord.source_local_date.is_(None),
            )
        ).one()
        return tuple(getattr(row, col.name) for col in GarminSourceRecord.__table__.columns)


@pytest.mark.parametrize("returned", [DAY, DAY + timedelta(days=1)])
def test_clipped_day_converges_without_retiring_legacy_then_full_range_finishes(saved, returned):
    end = DAY + timedelta(days=1)
    source_id = persist(
        saved,
        end,
        body=payload(returned, 21),
        legacy=True,
        window_start=DAY,
    )[0]
    before = originals(saved)
    legacy_before = legacy_projection(saved, source_id)
    first = apply_stored(saved, returned, returned)
    assert first.processed_count == 1 and first.retired_count == 0
    after_first = originals(saved)
    for _ in range(2):
        report = apply_stored(saved, returned, returned)
        assert report.processed_count == report.remaining_observation_count == 0
        assert originals(saved) == after_first
    assert legacy_projection(saved, source_id) == legacy_before
    assert {(r[1], r[3]) for r in projection(saved)} == {(None, 21), (returned, 21)}
    full = apply_stored(saved, DAY, end)
    assert full.processed_count == full.retired_count == 1
    assert {(r[1], r[3]) for r in projection(saved)} == {(returned, 21)}
    assert apply_stored(saved, DAY, end).processed_count == 0
    assert_originals_preserved(saved, before)


@pytest.mark.parametrize("returned", [DAY, DAY + timedelta(days=1)])
@pytest.mark.parametrize("second_clipped", [False, True])
def test_clipped_cap_one_advances_across_sources_and_later_full_transition(
    saved,
    returned,
    second_clipped,
):
    end = DAY + timedelta(days=1)
    first_source = persist(
        saved,
        end,
        body=payload(returned, 21),
        legacy=True,
        window_start=DAY,
        source=identity("clipped-first"),
    )[0]
    second_source = persist(
        saved,
        end if second_clipped else returned,
        body=payload(returned, 43),
        legacy=True,
        window_start=DAY if second_clipped else returned,
        source=identity("clipped-second"),
        at=RECEIPT + timedelta(hours=1),
    )[0]
    before = originals(saved)
    legacy_before = {sid: legacy_projection(saved, sid) for sid in (first_source, second_source)}
    first = apply_stored(saved, returned, returned)
    assert first.processed_count == first.remaining_observation_count == 1
    after_first = originals(saved)
    planned = apply_stored(saved, returned, returned, dry_run=True)
    assert planned.remaining_observation_count == 0
    assert originals(saved) == after_first
    second = apply_stored(saved, returned, returned)
    assert second.processed_count == 1 and second.remaining_observation_count == 0
    converged = originals(saved)
    third = apply_stored(saved, returned, returned)
    assert third.processed_count == third.remaining_observation_count == 0
    assert originals(saved) == converged
    assert {(r[0], r[1], r[3]) for r in projection(saved) if r[1] is not None} == {
        (first_source, returned, 21),
        (second_source, returned, 43),
    }
    assert legacy_projection(saved, first_source) == legacy_before[first_source]
    if second_clipped:
        assert legacy_projection(saved, second_source) == legacy_before[second_source]
    # A complete containing request must still finish each retained transition.
    reports = [apply_stored(saved, DAY, end) for _ in range(3)]
    assert reports[-1].processed_count == reports[-1].remaining_observation_count == 0
    assert {(r[0], r[1], r[3]) for r in projection(saved)} == {
        (first_source, returned, 21),
        (second_source, returned, 43),
    }
    assert_originals_preserved(saved, before)


@pytest.mark.parametrize("value,state", [("missing", "missing"), (None, "null"), (True, "invalid")])
def test_unproven_coverage_does_not_starve_later_source_or_retire_legacy(saved, value, state):
    body = payload(value=value)
    if value == "missing":
        del body["hrvSummary"]["weeklyAvg"]
    first_source = persist(saved, body=body, legacy=True, source=identity("unproven"))[0]
    second_source = persist(
        saved,
        value=43,
        legacy=True,
        source=identity("present"),
        at=RECEIPT + timedelta(hours=1),
    )[0]
    before = originals(saved)
    legacy_before = legacy_projection(saved, first_source)
    reports = [apply_stored(saved, DAY, DAY) for _ in range(3)]
    assert reports[0].remaining_observation_count == 1
    assert reports[1].remaining_observation_count == 0
    assert reports[2].processed_count == 0
    assert legacy_projection(saved, first_source) == legacy_before
    assert (first_source, DAY, state, None) in projection(saved)
    assert (second_source, DAY, "value", 43) in projection(saved)
    assert_originals_preserved(saved, before)


@pytest.mark.parametrize("full_range", [False, True])
def test_newer_same_day_dated_window_is_not_starved_by_old_legacy(saved, full_range):
    end = DAY + timedelta(days=1)
    persist(saved, end, body=payload(DAY, 21), legacy=True, window_start=DAY)
    persist(saved, value=43, at=RECEIPT + timedelta(hours=1))
    before = originals(saved)
    request_end = end if full_range else DAY
    report = apply_stored(saved, DAY, request_end)
    assert report.processed_count == report.retired_count == 1
    assert report.remaining_observation_count == 0
    assert {(r[1], r[3]) for r in projection(saved)} == {(DAY, 43)}
    assert apply_stored(saved, DAY, request_end).processed_count == 0
    assert_originals_preserved(saved, before)


def test_identity_replacement_rolls_back_atomically(saved, monkeypatch):
    persist(saved, legacy=True)
    original = reprocess._supersede_legacy_hrv

    def fail_after_retirement(*args):
        assert original(*args) == 1
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(reprocess, "_supersede_legacy_hrv", fail_after_retirement)
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    assert projection(saved)[0][1] is None
    assert len(projection(saved)) == 1


def test_corrupt_original_cannot_restore_or_retire(saved):
    persist(saved, legacy=True)
    path = next(saved[2].artifacts_root.rglob("*.json"))
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match="integrity mismatch"):
        run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    assert projection(saved)[0][1] is None


def test_wrong_returned_day_cannot_retire_requested_day(saved):
    persist(saved, legacy=True, body=payload(DAY + timedelta(days=1)))
    run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    assert projection(saved)[0][1] is None
    assert len(projection(saved)) == 1


@pytest.mark.parametrize("root", ["calendarDate", "date"])
def test_valid_nested_day_does_not_hide_invalid_present_root(root):
    body = dict(payload(), **{root: None})
    result = normalize(body)
    assert result.records[0].temporal.local_date is None
    assert not prepare(SURFACE, body, result, day=DAY).records


def test_duplicate_json_key_cannot_restore_or_retire(saved):
    raw = b'{"hrvSummary":{"calendarDate":"2099-01-02","weeklyAvg":31,"weeklyAvg":43}}'
    persist(saved, legacy=True, encoded=raw)
    with pytest.raises(ValueError, match="duplicate HRV JSON key"):
        run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    assert len(projection(saved)) == 1 and projection(saved)[0][1] is None


def test_hrv_byte_bound_cannot_restore_or_retire(saved, monkeypatch):
    persist(saved, legacy=True)
    monkeypatch.setattr(reprocess, "MAX_HRV_ARTIFACT_BYTES", 1)
    with pytest.raises(ValueError, match="byte bound unproven"):
        run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    assert len(projection(saved)) == 1 and projection(saved)[0][1] is None


def test_partial_missing_metric_does_not_supersede_legacy_identity(saved):
    persist(saved, legacy=True)
    body = payload()
    del body["hrvSummary"]["weeklyAvg"]
    persist(saved, body=body, legacy=True, at=RECEIPT + timedelta(hours=1))
    run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    rows = projection(saved)
    assert any(row[1] is None for row in rows)
    assert any(row[1] == DAY and row[2] == "missing" for row in rows)


def test_empty_day_cannot_claim_undated_legacy_membership(saved):
    persist(saved, legacy=True)
    persist(saved, body={}, legacy=True, at=RECEIPT + timedelta(hours=1))
    run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    assert len(projection(saved)) == 1
    assert projection(saved)[0][1] is None


def test_existing_overview_reads_restored_hrv_without_eligibility_change(saved):
    from healthcheck.web.overview_view import read_overview_values

    source_id = persist(saved, legacy=True)[0]
    run_garmin_reprocess(saved[0], start=DAY, end=DAY, streams=["hrv_status"])
    with saved[1]() as session:
        view = read_overview_values(session, start=DAY, end=DAY, selected_id=source_id)
    cell = view["garmin"]["hrv_weekly_average_ms"]
    assert cell["value"] == 31
    assert cell["date"] == DAY.isoformat()


def test_fake_production_sync_uses_hrv_date_and_keeps_correction_identity(tmp_path):
    from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
    from healthcheck.garmin.sync import GarminIncrementalSync
    from test_garmin_incremental_sync import FakeSyncClient, _engine_factory

    settings = Settings(data_dir=tmp_path / "runtime")
    for value in [31, 43]:
        report = GarminIncrementalSync(
            settings,
            client=FakeSyncClient(responses={"get_hrv_data": payload(value=value)}),
            auth_result=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED),
            clock=lambda: RECEIPT + timedelta(hours=value),
        ).run(as_of=DAY, trailing_window_days=1)
        assert report.status.value == "succeeded"
    engine, factory = _engine_factory(tmp_path)
    try:
        with factory() as session:
            rows = list(
                session.scalars(
                    select(GarminSourceRecord).where(
                        GarminSourceRecord.surface_code == "hrv_status",
                        GarminSourceRecord.projection_status == "current",
                    )
                )
            )
            assert len(rows) == 1 and rows[0].source_local_date == DAY
            metric = session.scalar(
                select(GarminRecordMetric).where(
                    GarminRecordMetric.record_id == rows[0].id,
                    GarminRecordMetric.metric_code == "hrv_weekly_average_ms",
                )
            )
            assert metric.value_number == 43
    finally:
        engine.dispose()
