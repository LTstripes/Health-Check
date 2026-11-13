"""Synthetic exact daily leaves, offline history and real HTML routes."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from healthcheck.config import Settings
from healthcheck.db.models import GarminSourceRecord
from healthcheck.garmin.daily_energy import FIELDS, read_daily_energy
from healthcheck.garmin.normalization import (
    NORMALIZATION_CONTRACT_VERSION,
    garmin_source_identity,
    normalize_garmin_payload,
)
from healthcheck.garmin.reprocess import run_garmin_reprocess
from healthcheck.web.statistics import statistics_energy_chart
from healthcheck.web.ui_app import create_ui_app
from overview_html import parse_overview
from test_garmin_completed_steps import acquire
from test_overview_completed import NOW
from test_stress_baseline import database as database

START = date(2099, 1, 1)


def test_statistics_chart_rounds_geometry_without_reconstructing_totals():
    rows = [
        {'total': 1234, 'bmr': 1000, 'active': 300, 'split': True},
        {'total': 0, 'bmr': None, 'active': None, 'split': False},
        {'total': None, 'bmr': 1500, 'active': 300, 'split': False},
    ]
    packet = {'rows': rows}
    before = deepcopy(packet)
    view = statistics_energy_chart(packet)
    assert packet == before
    assert view['ticks'] == [1500, 1000, 500, 0]
    assert view['bars'][0]['total'] != view['bars'][0]['bmr'] + view['bars'][0]['active']
    assert view['bars'][1]['total'] == 0
    assert view['bars'][2]['total'] is None
    assert statistics_energy_chart(None) is None


@pytest.mark.parametrize("key,leaf", FIELDS.items())
@pytest.mark.parametrize("value,state", [(None, "null"), (0, "value"), (123.5, "value"),
    (-1, "invalid"), (float("inf"), "invalid"), (float("nan"), "invalid"),
    (True, "invalid"), ("12", "invalid")])
def test_exact_daily_fields(key, leaf, value, state):
    payload = {"calendarDate": "2099-01-01", leaf: value,
               "wellnessKilocalories": 9999, "wellnessActiveKilocalories": 8888}
    result = normalize_garmin_payload(payload, stream="daily_health",
                                     source_identity=garmin_source_identity())
    assert result.contract_version == NORMALIZATION_CONTRACT_VERSION
    metric = result.records[0].metric(f"daily_{key}_kcal")
    assert metric.state.value == state
    assert metric.field_path == f"payload.{leaf}" and metric.unit == "kcal"
    assert metric.value == (value if state == "value" else None)
    for other in FIELDS.keys() - {key}:
        assert result.records[0].metric(f"daily_{other}_kcal").state.value == "missing"


def seed(database, days=2):
    _, _, session, store = database
    for index in range(days):
        saved = acquire(session, store, day=START + timedelta(days=index), at=NOW,
            extra={"totalKilocalories": 2000 + 200 * index,
                   "activeKilocalories": 500 + 100 * index, "bmrKilocalories": 1500 + 100 * index},
            window_day=START + timedelta(days=index))
        for record in session.query(GarminSourceRecord):
            record.surface_code = "daily_summary"
        session.commit()
    return saved.source.id


def read(database, source_id):
    return read_daily_energy(database[2], source_id=source_id, start=START,
                             end=START + timedelta(days=6))


def test_independent_averages_missing_and_read_only(database):
    source = seed(database)
    acquire(database[2], database[3], day=START + timedelta(days=2), at=NOW,
            extra={"totalKilocalories": None, "activeKilocalories": 0,
                   "bmrKilocalories": 1200, "wellnessKilocalories": 9000})
    statements = []
    event.listen(database[1], "before_cursor_execute", lambda _c, _u, statement, *_:
                 statements.append(statement.split()[0].lower()))
    result = read(database, source)
    assert result["summary"] == {
        "total": {"count": 2, "mean_value": Decimal(2100), "mean_display": "2 100"},
        "active": {"count": 3, "mean_value": Decimal(1100) / 3, "mean_display": "367"},
        "bmr": {"count": 3, "mean_value": Decimal(4300) / 3, "mean_display": "1 433"}}
    assert result["rows"][2]["total"] is None
    assert result["rows"][0]["split"]
    assert result["rows"][0]["evidence"][0]["raw_payload_id"]
    assert not {"insert", "update", "delete", "create", "alter"}.intersection(statements)
    assert all(row["total"] is None for row in read(database, None)["rows"])


def test_no_fill_from_two_components_or_wellness():
    for missing, leaf in FIELDS.items():
        payload = {"calendarDate": "2099-01-01", **dict.fromkeys(FIELDS.values(), 100),
                   "wellnessKilocalories": 100, "wellnessActiveKilocalories": 100,
                   "burnedKilocalories": 100, "restingCaloriesFromActivity": 100}
        del payload[leaf]
        result = normalize_garmin_payload(payload, stream="daily_health")
        assert result.records[0].metric(f"daily_{missing}_kcal").state.value == "missing"


def test_reader_bounds_and_thirty_days(database, monkeypatch):
    source = seed(database)
    result = read_daily_energy(database[2], source_id=source, start=START,
                             end=START + timedelta(days=29))
    assert len(result["rows"]) == 30 and result["summary"]["total"]["count"] == 2
    monkeypatch.setattr("healthcheck.garmin.daily_energy.MAX_METRICS", 1)
    result = read(database, source)
    assert result["reason"] == "search_incomplete"
    assert result["summary"]["total"]["mean_display"] is None
    assert read_daily_energy(database[2], source_id=source, start=START,
        end=START + timedelta(days=400))["reason"] == "unsupported_period"


def test_saved_raw_reprocess_restores_history_without_provider(database, monkeypatch):
    def old_normalizer(*args, **kwargs):
        result = normalize_garmin_payload(*args, **kwargs)
        return replace(result, contract_version="r02-garmin-normalization-contract-v2",
            records=tuple(replace(record, metrics=tuple(
                metric for metric in record.metrics if metric.capability_code != "daily_energy"))
                for record in result.records))
    with monkeypatch.context() as old:
        old.setattr("test_garmin_completed_steps.normalize_garmin_payload", old_normalizer)
        source = seed(database)
    session = database[2]
    assert read(database, source)["summary"]["total"]["count"] == 0
    session.rollback()
    report = run_garmin_reprocess(Settings(data_dir=database[0].root),
        start=START, end=START + timedelta(days=1), streams=["daily_summary"])
    assert report.status == "succeeded" and report.processed_count == 2
    assert report.as_dict()["reprocess"]["provider_requests"] == 0
    session.expire_all()
    assert read(database, source)["summary"]["total"]["mean_display"] == "2 100"
    session.rollback()
    again = run_garmin_reprocess(Settings(data_dir=database[0].root),
        start=START, end=START + timedelta(days=1), streams=["daily_summary"])
    assert again.processed_count == 0


@pytest.mark.parametrize("days", [0, 2, 7])
def test_overview_and_statistics_html(database, days, monkeypatch):
    class FrozenDatetime(type(NOW)):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)
    monkeypatch.setattr("healthcheck.web.pages.datetime", FrozenDatetime)
    source = seed(database, days=days) if days else None
    app, _ = create_ui_app(Settings(data_dir=database[0].root))
    app.state.engine = database[1]
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        params = {"start_date": "2099-01-01", "end_date": "2099-01-07",
                  "period_at": NOW.isoformat()}
        if source:
            params["garmin_source_id"] = source
        overview = client.get("/brief", params=params)
        assert overview.status_code == 200, overview.text
        card = overview.text.split('<div data-overview-energy>', 1)[1].split('</div>', 1)[0]
        assert 'Калории · оценка Garmin' in card
        if days:
            assert 'ккал/день' in card
        else:
            assert 'нет данных' in card and '0 ккал' not in card
        assert ('data-coverage-qualifier=' in card) == (days == 2)
        stats = client.get('/statistics', params={"period": "7", "end_date": "2099-01-07",
                                                  "garmin_source_id": source or ""})
        assert stats.status_code == 200
        section = stats.text.split('data-statistics-energy', 1)[1].split('</section>', 1)[0]
        assert '<table>' in section and '<caption>' in section and '<details' in section
        energy_block = parse_overview(stats.text).one('section', **{'data-statistics-energy': None})
        folded = energy_block.one('details')
        assert 'open' not in folded.attrs
        assert folded.one('summary').text == 'Таблица по дням и о данных'
        assert folded.one('table') is energy_block.one('table')
        assert energy_block.one('svg').find('g')
        assert section.count('data-energy-date=') == 7
        if days == 2:
            assert 'data-coverage-qualifier="2/7"' in section
            assert 'owner-value-low' in section
        if days == 7:
            assert 'data-coverage-qualifier=' not in section
        if days < 7:
            assert 'data-energy-state="missing"' in section and 'нет данных' in section
        if days:
            assert 'class="energy-bmr"' in section and 'class="energy-active"' in section
            assert 'tabindex="0"' in section
        else:
            assert '0 ккал' not in section
