"""Synthetic regressions for the owner-facing #104 report adapter."""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService
from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ui_app import create_ui_app


def _run(run_id: str = "run-1"):
    return SimpleNamespace(
        id=run_id,
        scope_key="synthetic:agreement",
        scope_lineage_key=f"lineage:{run_id}",
        window_key="2099-01-01:2099-01-14",
        requested_start_date=date(2099, 1, 1),
        requested_end_date=date(2099, 1, 14),
        cohort="all",
        completed_at=None,
        input_snapshot_hash="a" * 64,
        pairing_version="pair-v1",
        metric_version="metric-v1",
        statistic_version="stat-v1",
        rule_version="rule-v1",
        epoch_id="epoch-1",
        epoch_basis_json=json.dumps({"status": "unknown"}),
        status="succeeded",
    )


def _rows(*, cohort: str = "device_pair", count: int = 1, run_id: str = "run-1"):
    pairs = []
    metrics = []
    for index in range(count):
        wake_date = date(2099, 1, 1) + timedelta(days=index)
        pair_id = f"pair-{index}"
        pairs.append(
            SimpleNamespace(
                id=pair_id,
                run_id=run_id,
                ordinal=index,
                pair_key=f"{wake_date.isoformat()}:{cohort}:g-{index}:o-{index}",
                wake_date=wake_date,
                cohort=cohort,
                source_class=(
                    "fitbit_device"
                    if cohort == "device_pair"
                    else "google_wearables_family"
                ),
                pair_json=json.dumps(
                    {
                        "wake_date": wake_date.isoformat(),
                        "cohort": cohort,
                        "google_manually_edited": False,
                        "garmin_source_eligibility": {"eligible": True},
                        "google_source_eligibility": {"eligible": True},
                    }
                ),
            )
        )
        manifest = {
            "metric_definition": {"canonical_candidate": True},
            "google": {
                "provider": "google_fit",
                "record_id": f"google-{index}",
                "state": "value",
                "value": 100 + index,
                "unit": "seconds",
                "eligible": True,
                "is_zero": False,
                "evidence": {"immutable": True, "source_class": "fitbit_device"},
            },
            "garmin": {
                "provider": "garmin_connect",
                "record_id": f"garmin-{index}",
                "state": "value",
                "value": 100,
                "unit": "seconds",
                "eligible": True,
                "is_zero": False,
                "evidence": {"immutable": True, "source_class": "garmin_device"},
            },
        }
        metrics.append(
            SimpleNamespace(
                id=f"metric-{index}",
                pair_id=pair_id,
                metric_code="sleep_duration_asleep_seconds",
                variant=None,
                status="comparable",
                comparable=True,
                difference_number=float(index),
                difference_unit="seconds",
                reason=None,
                exclusion_basis=None,
                manifest_json=json.dumps(manifest),
            )
        )
    return pairs, metrics


def _service(run, pairs, metrics):
    service = object.__new__(SleepAgreementReportService)
    service.session = SimpleNamespace()
    service.repository = SimpleNamespace(
        get_by_id=lambda _run_id: run,
        validate_published=lambda _run_id: run,
        pairs_for_run=lambda _run_id: pairs,
        exclusions_for_run=lambda _run_id: [],
        metrics_for_run=lambda _run_id: metrics,
        latest_successful=lambda _lineage: run,
    )
    service._source_data_quality = lambda _pairs, _start, _end: []
    return service


def test_pre_n14_is_accumulation_only_and_keeps_cohort_visible():
    run = _run()
    pairs, metrics = _rows(count=13)
    payload = _service(run, pairs, metrics).report(run_id=run.id)

    group = payload["groups"][0]
    assert payload["mode"] == "accumulating"
    assert group["cohort"] == "device_pair"
    assert group["source_attribution"]["cohort_label"] == "Fitbit device pair"
    assert group["n"] == 13
    assert group["progress"]["remaining_n"] == 1
    assert group["accepted_statistics"] is None
    assert group["chart"]["point_count"] == 13


def test_n14_exposes_only_canonical_statistics_and_family_pair_stays_exploratory():
    run = _run()
    pairs, metrics = _rows(cohort="family_pair", count=14)
    payload = _service(run, pairs, metrics).report(run_id=run.id)

    group = payload["groups"][0]
    assert payload["mode"] == "exploratory"
    assert group["cohort"] == "family_pair"
    assert group["source_attribution"]["cohort_label"] == "Google wearable family pair"
    assert group["accepted_statistics"]["n"] == 14
    assert group["accepted_statistics"]["gate"]["canonical_switch_applied"] is False
    assert group["accepted_statistics"]["gate"]["canonical_proposal_eligible"] is False


def test_night_drilldown_uses_frozen_metadata_without_raw_payload_body():
    run = _run()
    pairs, metrics = _rows(count=1)
    payload = _service(run, pairs, metrics).night_detail(run.id, wake_date=pairs[0].wake_date)

    assert payload["nights"][0]["wake_date"] == "2099-01-01"
    assert payload["nights"][0]["metrics"][0]["status"] == "comparable"
    assert "raw_payload_body" not in json.dumps(payload)
    assert payload["claims"] == {"accuracy": "not_assessed", "canonical_switch": "not_applied"}


def test_empty_report_api_and_owner_page_are_honest(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())

    with TestClient(app) as client:
        report = client.get("/api/agreement/report")
        assert report.status_code == 200
        assert report.json()["mode"] == "unavailable"
        page = client.get("/agreement")
        assert page.status_code == 200
        assert "Accuracy is not assessed" in page.text
        assert client.get("/static/agreement.js").status_code == 200
