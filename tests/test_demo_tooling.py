from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import func, select

from healthcheck.analytics.period_summary import SLEEP_CODE, PeriodSummaryService
from healthcheck.analytics.sleep_pairing import (
    FAMILY_PAIR,
    SleepPairingQuery,
    read_persisted_sleep_pairing,
)
from healthcheck.config import Settings
from healthcheck.context import ContextService
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import (
    GarminActivityRecord,
    GarminRecordMetric,
    GarminSleepRecord,
    GoogleRecordMetric,
    GoogleSleepRecord,
)
from healthcheck.demo import (
    DEMO_ANCHOR_DATE,
    DEMO_MARKER_NAME,
    DEMO_SEED_ID,
    DEMO_SOURCE_APPLICATION,
    DemoSeedError,
    _synthetic_uploads,
    seed_demo,
)
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.synthetic import encode_synthetic_png, weigh_in_payload
from healthcheck.runtime import prepare_runtime, resolve_runtime_paths
from healthcheck.uat import (
    _HttpResult,
    format_smoke_results,
    run_smoke,
    smoke_exit_code,
)


def _file_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _seed_legacy_v1_profile(settings: Settings) -> None:
    """Build a genuine v1-shaped runtime through the accepted photo service."""

    paths = prepare_runtime(settings)
    migrate_database(paths)
    uploads, expected_candidates = _synthetic_uploads()
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            service = PhotoImportService(
                session,
                paths,
                FakeImageMeasurementExtractor(version="synthetic-demo-v1"),
            )
            imported = service.import_photos(
                uploads,
                timezone="UTC",
                provider_code="xiaomi_home",
            )
            candidate_ids = [
                candidate_id for item in imported.items for candidate_id in item.candidate_ids
            ]
            assert len(candidate_ids) == expected_candidates
            service.confirm(candidate_ids, actor="synthetic-demo")
    finally:
        engine.dispose()
    (settings.data_dir / DEMO_MARKER_NAME).write_text(
        json.dumps(
            {
                "format_version": 1,
                "seed_id": "r01-six-month-synthetic-v1",
                "label": "synthetic demo data",
                "weigh_in_count": len(uploads),
                "candidate_count": expected_candidates,
            }
        ),
        encoding="utf-8",
    )



def _demo_digest(data_dir: Path) -> dict[str, object]:
    """Return a deterministic content digest of the seeded synthetic domains."""

    settings = Settings(data_dir=data_dir)
    paths = resolve_runtime_paths(settings)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            garmin_durations = dict(
                session.execute(
                    select(GarminRecordMetric.record_id, GarminRecordMetric.value_number).where(
                        GarminRecordMetric.metric_code == "sleep_duration_seconds"
                    )
                ).all()
            )
            google_asleep = dict(
                session.execute(
                    select(GoogleRecordMetric.record_id, GoogleRecordMetric.value_number).where(
                        GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"
                    )
                ).all()
            )
            activity_rows = {
                record_id: (activity_type, day)
                for record_id, activity_type, day in session.execute(
                    select(
                        GarminActivityRecord.record_id,
                        GarminActivityRecord.activity_type,
                        GarminRecordMetric.value_number,
                    ).join(
                        GarminRecordMetric,
                        GarminRecordMetric.record_id == GarminActivityRecord.record_id,
                    ).where(GarminRecordMetric.metric_code == "duration_seconds")
                )
            }
            return {
                "garmin_sleep": sorted(
                    f"{wake.isoformat()}|{garmin_durations.get(record_id)}"
                    for record_id, wake in session.execute(
                        select(GarminSleepRecord.record_id, GarminSleepRecord.wake_date)
                    )
                ),
                "google_sleep": sorted(
                    f"{wake.isoformat()}|{google_asleep.get(record_id)}"
                    for record_id, wake in session.execute(
                        select(GoogleSleepRecord.record_id, GoogleSleepRecord.wake_date)
                    )
                ),
                "activities": sorted(
                    f"{kind}|{day}" for kind, day in activity_rows.values()
                ),
                "context": [
                    f"{note.temporal.kind}|{note.capture_source}|{note.original_text}"
                    for note in ContextService(session).list(limit=100)
                ],
            }
    finally:
        engine.dispose()


def test_seed_demo_is_idempotent_and_exposes_dashboard_data(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")

    first = seed_demo(settings)
    second = seed_demo(settings)

    assert first.created is True
    assert first.weigh_in_count == 26
    assert first.candidate_count == 59
    assert first.garmin_sleep_count == 25
    assert first.garmin_activity_count == 6
    assert first.google_sleep_count == 26
    assert first.context_count == 6
    assert second.created is False
    assert second.weigh_in_count == first.weigh_in_count
    assert second.candidate_count == first.candidate_count
    assert second.garmin_sleep_count == first.garmin_sleep_count
    assert second.garmin_activity_count == first.garmin_activity_count
    assert second.google_sleep_count == first.google_sleep_count
    assert second.context_count == first.context_count

    marker_data = json.loads((settings.data_dir / DEMO_MARKER_NAME).read_text(encoding="utf-8"))
    assert marker_data["label"] == "synthetic demo data"
    assert marker_data["seed_id"] == DEMO_SEED_ID
    assert marker_data["format_version"] == 2
    assert marker_data["anchor_date"] == DEMO_ANCHOR_DATE.isoformat()


def test_seed_demo_is_reproducible_across_fresh_runtimes(tmp_path: Path) -> None:
    first = seed_demo(Settings(data_dir=tmp_path / "demo-a"))
    second = seed_demo(Settings(data_dir=tmp_path / "demo-b"))

    assert first.created is True
    assert second.created is True
    assert _demo_digest(first.data_dir) == _demo_digest(second.data_dir)


def test_seed_demo_keeps_missing_and_partial_days_honest(tmp_path: Path) -> None:
    result = seed_demo(Settings(data_dir=tmp_path / "synthetic-demo"))
    paths = resolve_runtime_paths(Settings(data_dir=result.data_dir))
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            garmin_duration_values = session.scalar(
                select(func.count())
                .select_from(GarminRecordMetric)
                .where(
                    GarminRecordMetric.metric_code == "sleep_duration_seconds",
                    GarminRecordMetric.state == "value",
                )
            )
            garmin_score_values = session.scalar(
                select(func.count())
                .select_from(GarminRecordMetric)
                .where(
                    GarminRecordMetric.metric_code == "sleep_score",
                    GarminRecordMetric.state == "value",
                )
            )
            google_asleep_values = session.scalar(
                select(func.count())
                .select_from(GoogleRecordMetric)
                .where(
                    GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep",
                    GoogleRecordMetric.state == "value",
                )
            )
            # Three sparse Garmin nights keep only the duration; missing days
            # produce no record at all, and the Google partial night keeps a
            # non-value state instead of a fabricated zero.
            assert garmin_duration_values == 25
            assert garmin_score_values == 22
            assert google_asleep_values == 25

            pairing = read_persisted_sleep_pairing(
                session, SleepPairingQuery(cohort=FAMILY_PAIR)
            )
            assert len(pairing.pairs) == 19
            assert any(pair.google_manually_edited is True for pair in pairing.pairs)
            reasons = {exclusion.reason for exclusion in pairing.exclusions}
            assert {"missing_garmin_main", "missing_google_main", "google_nap_only"} <= reasons

            for days, expected_sessions, expected_missing in ((7, 2, 1), (30, 6, 5)):
                packet = PeriodSummaryService(session).build(
                    end_date=DEMO_ANCHOR_DATE, days=days
                )
                garmin = next(
                    side for side in packet["sides"] if side["provider_code"] == "garmin_connect"
                )
                google = next(
                    side for side in packet["sides"] if side["provider_code"] == "google_health"
                )
                assert (
                    garmin["metrics"]["activity_session_count"]["aggregation"]["value"]
                    == expected_sessions
                )
                assert garmin["metrics"][SLEEP_CODE]["state"] == "observed"
                assert google["metrics"][SLEEP_CODE]["state"] == "observed"
                assert garmin["metrics"][SLEEP_CODE]["missing_day_count"] == expected_missing
    finally:
        engine.dispose()


def test_seed_demo_reset_requires_owned_marker_and_does_not_touch_unknown_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing-profile"
    target.mkdir()
    sentinel = target / "private-looking.txt"
    sentinel.write_text("must remain", encoding="utf-8")

    with pytest.raises(DemoSeedError, match="non-empty"):
        seed_demo(Settings(data_dir=target), reset=True)

    assert sentinel.read_text(encoding="utf-8") == "must remain"


def test_seed_demo_reset_rebuilds_only_marked_profile(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")
    seed_demo(settings)
    extra = settings.data_dir / "owner-note.txt"
    extra.write_text("leave this file", encoding="utf-8")

    result = seed_demo(settings, reset=True)

    assert result.created is True
    assert result.reset is True
    assert extra.read_text(encoding="utf-8") == "leave this file"


def test_seed_demo_reset_preflight_preserves_state_on_invalid_artifacts(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")
    seed_demo(settings)
    database = settings.data_dir / "healthcheck.db"
    marker = settings.data_dir / DEMO_MARKER_NAME
    artifacts = settings.data_dir / "artifacts"
    saved_database = database.read_bytes()
    saved_marker = marker.read_bytes()
    saved_artifacts = tmp_path / "saved-artifacts"
    artifacts.rename(saved_artifacts)
    artifacts.write_bytes(b"not a directory")

    with pytest.raises(DemoSeedError, match="artifacts directory"):
        seed_demo(settings, reset=True)

    assert database.read_bytes() == saved_database
    assert marker.read_bytes() == saved_marker
    assert artifacts.read_bytes() == b"not a directory"
    assert saved_artifacts.is_dir()


def test_seed_demo_rejects_checkout_target(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(DemoSeedError, match="outside the checkout"):
        seed_demo(Settings(data_dir=Path(__file__).resolve().parents[1]))


def test_seed_demo_rejects_target_inside_another_checkout(tmp_path: Path) -> None:
    target = tmp_path / "other-checkout"
    target.mkdir()
    (target / ".git").write_text("gitdir: somewhere else\n", encoding="utf-8")

    with pytest.raises(DemoSeedError, match="checkout or workspace"):
        seed_demo(Settings(data_dir=target))

    assert not (target / "healthcheck.db").exists()


def test_seed_demo_rejects_junction_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "junctioned-demo"
    target.mkdir()
    monkeypatch.setattr(Path, "is_junction", lambda self: self == target)

    with pytest.raises(DemoSeedError, match="symlink or junction"):
        seed_demo(Settings(data_dir=target))

    assert not (target / "healthcheck.db").exists()


def test_seed_demo_rejects_real_directory_junction_on_windows(tmp_path: Path) -> None:
    if os.name != "nt":
        return
    target = tmp_path / "junction-target"
    target.mkdir()
    link = tmp_path / "junction-link"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    with pytest.raises(DemoSeedError, match="symlink or junction"):
        seed_demo(Settings(data_dir=link))


def test_seed_demo_reset_rejects_junctioned_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")
    seed_demo(settings)
    artifacts = settings.data_dir / "artifacts"
    database = settings.data_dir / "healthcheck.db"
    saved_database = database.read_bytes()
    monkeypatch.setattr(Path, "is_junction", lambda self: self == artifacts)

    with pytest.raises(DemoSeedError, match="artifacts directory"):
        seed_demo(settings, reset=True)

    assert database.read_bytes() == saved_database


def test_seed_demo_legacy_marker_on_current_content_fails_closed(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")
    seed_demo(settings)
    marker = settings.data_dir / DEMO_MARKER_NAME
    marker.write_text(
        json.dumps(
            {
                "format_version": 1,
                "seed_id": "r01-six-month-synthetic-v1",
                "label": "synthetic demo data",
                "weigh_in_count": 26,
                "candidate_count": 59,
            }
        ),
        encoding="utf-8",
    )
    database = settings.data_dir / "healthcheck.db"

    with pytest.raises(DemoSeedError, match="--reset"):
        seed_demo(settings)

    saved_database = database.read_bytes()
    saved_marker = marker.read_bytes()

    # A legacy marker on current-content rows is inconsistent ownership; the
    # content preflight must refuse to delete anything.
    with pytest.raises(DemoSeedError, match="does not match"):
        seed_demo(settings, reset=True)

    assert database.read_bytes() == saved_database
    assert marker.read_bytes() == saved_marker


def test_seed_demo_genuine_legacy_v1_reset_rebuilds(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")
    settings.data_dir.mkdir(parents=True)
    _seed_legacy_v1_profile(settings)
    marker = settings.data_dir / DEMO_MARKER_NAME

    with pytest.raises(DemoSeedError, match="--reset"):
        seed_demo(settings)

    rebuilt = seed_demo(settings, reset=True)

    assert rebuilt.created is True
    assert rebuilt.reset is True
    assert rebuilt.weigh_in_count == 26
    assert rebuilt.garmin_sleep_count == 25
    assert rebuilt.google_sleep_count == 26
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    assert marker_data["seed_id"] == DEMO_SEED_ID
    assert marker_data["format_version"] == 2


def test_seed_demo_reset_rejects_foreign_database_with_copied_marker(
    tmp_path: Path,
) -> None:
    donor = Settings(data_dir=tmp_path / "donor")
    seed_demo(donor)

    target = tmp_path / "foreign-profile"
    target.mkdir()
    settings = Settings(data_dir=target)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    (target / DEMO_MARKER_NAME).write_bytes(
        (donor.data_dir / DEMO_MARKER_NAME).read_bytes()
    )
    saved = _file_digest(target)

    with pytest.raises(DemoSeedError, match="does not match"):
        seed_demo(settings, reset=True)

    assert _file_digest(target) == saved


def test_seed_demo_reset_rejects_extra_foreign_record(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")
    seed_demo(settings)
    paths = resolve_runtime_paths(settings)
    payload = weigh_in_payload(
        source_local_date=DEMO_ANCHOR_DATE,
        weight_kg=71.5,
        source_application=DEMO_SOURCE_APPLICATION,
    )
    image = encode_synthetic_png(payload)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            service = PhotoImportService(
                session,
                paths,
                FakeImageMeasurementExtractor(version="synthetic-demo-v1"),
            )
            imported = service.import_photos(
                [PhotoUpload(filename="extra.png", content=image, declared_media_type="image/png")],
                timezone="UTC",
                provider_code="xiaomi_home",
            )
            candidate_ids = [
                candidate_id for item in imported.items for candidate_id in item.candidate_ids
            ]
            service.confirm(candidate_ids, actor="extra-record")
    finally:
        engine.dispose()
    saved = _file_digest(settings.data_dir)

    with pytest.raises(DemoSeedError, match="does not match"):
        seed_demo(settings, reset=True)

    assert _file_digest(settings.data_dir) == saved


def test_seed_demo_rejects_junction_alias_into_another_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "other-checkout"
    nested = checkout / "nested"
    nested.mkdir(parents=True)
    (checkout / ".git").write_text("gitdir: somewhere else\n", encoding="utf-8")

    alias = tmp_path / "alias"
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(nested)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
    else:
        alias.symlink_to(nested, target_is_directory=True)

    with pytest.raises(DemoSeedError, match="checkout or workspace"):
        seed_demo(Settings(data_dir=alias / "demo"))

    assert not (nested / "demo").exists()


def test_seed_demo_reset_refuses_foreign_marker(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "synthetic-demo")
    seed_demo(settings)
    marker = settings.data_dir / DEMO_MARKER_NAME
    marker.write_text(
        json.dumps(
            {
                "format_version": 2,
                "seed_id": "someone-elses-profile",
                "label": "synthetic demo data",
                "weigh_in_count": 1,
                "candidate_count": 1,
                "garmin_sleep_count": 1,
                "garmin_activity_count": 1,
                "google_sleep_count": 1,
                "context_count": 1,
            }
        ),
        encoding="utf-8",
    )
    database = settings.data_dir / "healthcheck.db"
    saved_database = database.read_bytes()

    with pytest.raises(DemoSeedError, match="not owned"):
        seed_demo(settings, reset=True)

    assert database.read_bytes() == saved_database


def test_smoke_reports_pass_skip_and_never_prints_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"Bearer private-token; 80.00 kg"
    responses = {
        ("http://ui/healthz", "GET"): _HttpResult(
            200, "application/json", b'{"status":"ok","service":"loopback-ui"}'
        ),
        ("http://ui/", "GET"): _HttpResult(200, "text/html", secret),
        ("http://ui/api/weight/series", "GET"): _HttpResult(
            200, "application/json", b'{"raw_points":[],"composition_by_group":{}}'
        ),
        ("http://ui/api/weight/summary", "GET"): _HttpResult(
            200, "application/json", b'{"trend":{},"latest_composition":{},"coverage":null}'
        ),
        ("http://ui/api/ingest/openscale", "POST"): _HttpResult(
            404, "application/json", b"private response"
        ),
    }

    def fake_request(url: str, *, method: str = "GET", timeout: float) -> _HttpResult:
        del timeout
        return responses[(url, method)]

    monkeypatch.setattr("healthcheck.uat._request", fake_request)
    results = run_smoke(ui_url="http://ui")
    rendered = format_smoke_results(results)

    assert smoke_exit_code(results) == 0
    assert "OVERALL PASS" in rendered
    assert "SKIP /ingest/healthz" in rendered
    assert "private-token" not in rendered
    assert "80.00" not in rendered


def test_smoke_checks_ingest_liveness_and_route_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        ("http://ui/healthz", "GET"): _HttpResult(
            200, "application/json", b'{"status":"ok","service":"loopback-ui"}'
        ),
        ("http://ui/", "GET"): _HttpResult(200, "text/html", b"synthetic dashboard"),
        ("http://ui/api/weight/series", "GET"): _HttpResult(
            200, "application/json", b'{"raw_points":[],"composition_by_group":{}}'
        ),
        ("http://ui/api/weight/summary", "GET"): _HttpResult(
            200, "application/json", b'{"trend":{},"latest_composition":{},"coverage":null}'
        ),
        ("http://ui/api/ingest/openscale", "POST"): _HttpResult(404, "", b""),
        ("http://ingest/healthz", "GET"): _HttpResult(
            200, "application/json", b'{"status":"ok","service":"ingest"}'
        ),
        ("http://ingest/", "GET"): _HttpResult(404, "", b""),
        ("http://ingest/api/weight/series", "GET"): _HttpResult(404, "", b""),
        ("http://ingest/static/dashboard.js", "GET"): _HttpResult(404, "", b""),
    }

    def fake_request(url: str, *, method: str = "GET", timeout: float) -> _HttpResult:
        del timeout
        return responses[(url, method)]

    monkeypatch.setattr("healthcheck.uat._request", fake_request)
    results = run_smoke(ui_url="http://ui", ingest_url="http://ingest")

    assert smoke_exit_code(results) == 0
    assert all(result.status == "PASS" for result in results)
    assert "/ingest/healthz" in format_smoke_results(results)
