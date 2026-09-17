"""Synthetic contract checks for the issue #136 sleep-agreement operator command."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, select

from healthcheck import cli
from healthcheck.db.models import (
    AgreementRun,
    GarminSleepRecord,
    GarminSourceRecord,
    GoogleRecordMetric,
    GoogleRecordSourceEvidence,
    GoogleSourceRecord,
)
from test_sleep_account_cohort import (
    COHORT,
    START,
    _garmin,
    _google,
)

pytest_plugins = ("test_sleep_pairing",)


def _args(paths, *, start: date = START, end: date = START, cohort: str = COHORT) -> list[str]:
    data_dir = paths if isinstance(paths, Path) else paths.root
    return [
        "sleep-agreement-build",
        "--data-dir",
        str(data_dir),
        "--cohort",
        cohort,
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
    ]


def test_build_persists_real_projection_is_idempotent_and_verifies_report(
    pairing_database, capsys, monkeypatch
):
    session, paths = pairing_database
    for offset in range(14):
        wake = START + timedelta(days=offset)
        _garmin(session, paths, wake)
        _google(session, paths, wake)
    session.commit()
    source_models = (
        GarminSleepRecord,
        GarminSourceRecord,
        GoogleSourceRecord,
        GoogleRecordMetric,
        GoogleRecordSourceEvidence,
    )
    source_counts = {
        model: session.scalar(select(func.count()).select_from(model)) for model in source_models
    }

    def provider_call(*_args, **_kwargs):
        raise AssertionError("sleep-agreement-build must not call a provider")

    monkeypatch.setattr(cli, "GarminAuthService", provider_call)
    monkeypatch.setattr(cli, "GoogleAuthService", provider_call)
    assert cli.main(_args(paths, end=START + timedelta(days=13))) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "succeeded"
    assert first["created"] is True
    assert first["run_status"] == "succeeded"
    assert first["pair_count"] == 14
    assert first["exploratory_only"] is True
    assert first["canonical_eligible"] is False
    assert first["report_verification"]["status"] == "verified"
    assert first["report_verification"]["mode"] == "exploratory"
    assert first["report_verification"]["group_count"] > 0
    first_text = json.dumps(first)
    assert "28800" not in first_text
    assert "synthetic-account" not in first_text

    assert cli.main(_args(paths, end=START + timedelta(days=13))) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["created"] is False
    assert second["pair_count"] == first["pair_count"]
    assert session.scalar(select(func.count()).select_from(AgreementRun)) == 1
    assert {
        model: session.scalar(select(func.count()).select_from(model)) for model in source_models
    } == source_counts


def test_build_under_n14_persists_but_returns_honest_insufficient_status(
    pairing_database, capsys
):
    session, paths = pairing_database
    for offset in range(13):
        wake = START + timedelta(days=offset)
        _garmin(session, paths, wake)
        _google(session, paths, wake)
    session.commit()

    assert cli.main(_args(paths, end=START + timedelta(days=12))) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "insufficient"
    assert payload["run_status"] == "succeeded"
    assert payload["pair_count"] == 13
    assert payload["report_verification"]["mode"] == "accumulating"
    assert payload["canonical_eligible"] is False


def test_build_rejects_invalid_window_and_cohort(capsys, tmp_path):
    for args in (
        [
            "sleep-agreement-build",
            "--data-dir",
            str(tmp_path),
            "--start",
            "2099-01-03",
            "--end",
            "2099-01-02",
        ],
        [
            "sleep-agreement-build",
            "--data-dir",
            str(tmp_path),
            "--start",
            "not-a-date",
            "--end",
            "2099-01-02",
        ],
        [
            "sleep-agreement-build",
            "--data-dir",
            str(tmp_path),
            "--cohort",
            "unsupported",
            "--start",
            "2099-01-02",
            "--end",
            "2099-01-02",
        ],
    ):
        assert cli.main(args) == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "failed"
        assert payload["privacy"] == {
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
            "tokens_emitted": False,
        }


def test_build_missing_runtime_fails_closed_without_bootstrap(capsys, tmp_path):
    runtime = tmp_path / "missing-runtime"

    code = cli.main(_args(runtime))

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"] == {
        "error_class": "runtime",
        "error_code": "runtime_missing",
        "http_status": None,
    }
    assert payload["privacy"] == {
        "raw_values_emitted": False,
        "private_identifiers_emitted": False,
        "tokens_emitted": False,
    }
    assert not runtime.exists()
    assert not (runtime / "config.toml").exists()
    assert not (runtime / "healthcheck.db").exists()
    assert not (runtime / "artifacts").exists()


def test_build_unestablished_runtime_fails_closed_without_bootstrap(capsys, tmp_path):
    runtime = tmp_path / "unestablished-runtime"
    runtime.mkdir()

    code = cli.main(_args(runtime))

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"]["error_code"] == "runtime_not_established"
    assert not (runtime / "config.toml").exists()
    assert not (runtime / "healthcheck.db").exists()
    assert not (runtime / "artifacts").exists()
