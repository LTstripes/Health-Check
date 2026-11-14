"""Synthetic normalization, saved replay, weekly coverage, and actual HTML routes."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from healthcheck.config import Settings
from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
from healthcheck.garmin.intensity_minutes import FIELDS, read_intensity_minutes
from healthcheck.garmin.normalization import (
    NORMALIZATION_CONTRACT_VERSION,
    garmin_source_identity,
    normalize_garmin_payload,
)
from healthcheck.garmin.reprocess import run_garmin_reprocess
from healthcheck.garmin.training import persist_training_payload
from healthcheck.web.statistics import templates as statistics_templates
from healthcheck.web.ui_app import create_ui_app
from overview_html import parse_overview
from test_garmin_completed_steps import acquire
from test_overview_completed import NOW
from test_stress_baseline import database as database

MONDAY = date(2099, 1, 5)


@pytest.mark.parametrize("key,spec", FIELDS.items())
@pytest.mark.parametrize("value,state", [
    (0, "value"), (12.5, "value"), (None, "null"), (-1, "invalid"),
    (float("inf"), "invalid"), (float("-inf"), "invalid"), (float("nan"), "invalid"),
    (True, "invalid"), ("12", "invalid"), ({}, "invalid"), ([], "invalid"),
])
def test_exact_leaves_independent_values_and_no_device_claim(key, spec, value, state):
    code, leaf = spec
    result = normalize_garmin_payload({"calendarDate": MONDAY.isoformat(), leaf: value,
        "weeklyIntensityMinutes": 900, "intensityMinutes": 800,
        "dailyModerateIntensityMinutes": 700}, stream="daily_health",
        source_identity=garmin_source_identity())
    assert result.contract_version == NORMALIZATION_CONTRACT_VERSION
    assert result.contract_version == "r02-garmin-normalization-contract-v5"
    metric = result.records[0].metric(code)
    assert metric.state.value == state
    assert metric.value == (value if state == "value" else None)
    assert metric.unit == "min" and metric.field_path == f"payload.{leaf}"
    assert not metric.source_device_attributed
    for other, (other_code, _) in FIELDS.items():
        if other != key:
            assert result.records[0].metric(other_code).state.value == "missing"


def seed(database, days=7, *, start=MONDAY, extra=None, account="synthetic-account"):
    session, store = database[2:]
    for index in range(days):
        day = start + timedelta(days=index)
        saved = acquire(session, store, day=day, at=NOW, window_day=day, account=account,
            extra=extra if extra is not None else {"moderateIntensityMinutes": 10,
                "vigorousIntensityMinutes": 5, "intensityMinutesGoal": 150})
        for record in saved.records:
            record.surface_code = "daily_summary"
        session.commit()
    return saved.source.id


def read(database, source, *, start=MONDAY, end=None):
    return read_intensity_minutes(database[2], source_id=source,
        start=start, end=end or start + timedelta(days=6))


def test_full_week_and_read_only(database):
    source = seed(database)
    statements = []
    event.listen(database[1], "before_cursor_execute", lambda _c, _u, statement, *_:
                 statements.append(statement.split()[0].lower()))
    result = read(database, source)
    week = result["weeks"][0]
    assert week["complete"] and week["count"] == week["days"] == 7
    assert (week["moderate"], week["vigorous"], week["total"]) == (70, 35, 140)
    assert week["goal"] == 150 and week["goal_date"] == MONDAY + timedelta(days=6)
    assert result["rows"][0]["evidence"][0]["raw_payload_id"]
    assert not {"insert", "update", "delete", "create", "alter"}.intersection(statements)


@pytest.mark.parametrize("mutation", [None, "mixed", "metricless", "daily_summary"])
def test_null_surface_training_records_do_not_collide_unless_summary_candidates(database, mutation):
    source = seed(database, days=1,
                  account=garmin_source_identity(source_kind="provider").source_instance_id)
    session, store = database[2:]
    persist_training_payload(session, store, surface="training_readiness", requested_date=MONDAY,
        payload=[{"calendarDate": MONDAY.isoformat(), "timestamp": f"{MONDAY}T{hour}:00:00",
                  "score": 75} for hour in ("06", "12")], received_at=NOW)
    session.commit()
    training = session.query(GarminSourceRecord).filter_by(surface_code=None).all()
    assert len(training) == 2
    for record in training:
        assert record.garmin_source_id == source and record.stream_code == "daily_health"
        assert record.projection_status == "current" and record.source_local_date == MONDAY
        metrics = session.query(GarminRecordMetric).filter_by(record_id=record.id).all()
        assert metrics and all(metric.capability_code == "garmin_training" for metric in metrics)
    if mutation == "mixed":
        # A non-intensity metric must still make this a legacy summary candidate.
        session.add(GarminRecordMetric(record_id=training[0].id, capability_code="steps",
            metric_code="steps", field_path="payload.totalSteps", state="value",
            value_number=17, unit="count"))
    elif mutation == "metricless":
        session.query(GarminRecordMetric).filter_by(record_id=training[0].id).delete()
    elif mutation == "daily_summary":
        training[0].surface_code = "daily_summary"
    session.commit()
    packet = read(database, source, end=MONDAY)
    row = packet["rows"][0]
    if mutation is None:
        assert (row["moderate"], row["vigorous"], row["total"]) == (10, 5, 20)
        assert packet["weeks"][0]["total"] == 20
        assert packet["weeks"][0]["complete"]
        assert len(row["evidence"]) == 3
    else:
        assert all(row[key] is None for key in (*FIELDS, "total"))
        assert packet["weeks"][0]["total"] is None
        assert packet["weeks"][0]["count"] == 0


def test_partial_days_never_fill_or_count_unpaired_minutes(database):
    source = seed(database, days=2)
    seed(database, days=1, start=MONDAY + timedelta(days=2), extra={
        "moderateIntensityMinutes": 30, "vigorousIntensityMinutes": None,
        "intensityMinutesGoal": 160})
    seed(database, days=1, start=MONDAY + timedelta(days=3), extra={
        "moderateIntensityMinutes": None, "vigorousIntensityMinutes": 0,
        "intensityMinutesGoal": None})
    result = read(database, source)
    week = result["weeks"][0]
    assert not week["complete"] and week["count"] == 2 and week["days"] == 7
    assert week["total"] == 40 and week["moderate"] == 50 and week["vigorous"] == 10
    assert week["moderate_count"] == week["vigorous_count"] == 3
    assert week["goal"] == 160 and week["goal_date"] == MONDAY + timedelta(days=2)
    assert result["rows"][2]["total"] is None
    assert result["rows"][3]["vigorous"] == 0 and result["rows"][3]["total"] is None
    assert all(result["rows"][4][key] is None for key in (*FIELDS, "total"))


def test_window_crosses_week_boundary_and_goal_does_not_carry(database):
    source = seed(database)
    seed(database, days=1, start=MONDAY + timedelta(days=7), extra={
        "moderateIntensityMinutes": 0, "vigorousIntensityMinutes": 0})
    result = read(database, source, start=MONDAY + timedelta(days=2),
                  end=MONDAY + timedelta(days=8))
    assert result["start"] == MONDAY and result["requested_start"] == MONDAY + timedelta(days=2)
    first, second = result["weeks"]
    assert first["total"] == 140 and first["complete"]
    assert second["total"] == 0 and second["count"] == 1 and second["days"] == 2
    assert not second["complete"] and second["goal"] is None
    assert result["rows"][-1]["total"] is None
    assert read(database, source, end=MONDAY)["weeks"][0]["complete"]


def test_no_source_no_values_and_bounds(database, monkeypatch):
    source = seed(database, days=1, extra={"intensityMinutesGoal": 0})
    week = read(database, source)["weeks"][0]
    assert week["goal"] == 0 and week["total"] is None and week["count"] == 0
    assert read(database, None)["reason"] == "source_not_selected"
    assert read(database, source, end=MONDAY - timedelta(days=1))["reason"] == "unsupported_period"
    too_long = read(database, source, end=MONDAY + timedelta(days=366))
    assert too_long["reason"] == "unsupported_period"
    assert len(read(database, source, end=MONDAY + timedelta(days=29))["rows"]) == 30
    monkeypatch.setattr("healthcheck.garmin.intensity_minutes.MAX_METRICS", 1)
    result = read(database, source)
    assert result["reason"] == "search_incomplete" and result["weeks"][0]["total"] is None


@pytest.mark.parametrize("mutation", ["source", "surface", "stream", "retired", "path", "unit",
    "capability", "invalid", "collision", "metricless_collision"])
def test_source_currentness_collision_and_metric_guards(database, mutation):
    source = seed(database, days=1)
    session = database[2]
    record = session.query(GarminSourceRecord).one()
    metric = session.query(GarminRecordMetric).filter_by(
        record_id=record.id, metric_code="daily_moderate_intensity_min").one()
    if mutation == "source":
        source = seed(database, days=1, account="other", extra={})
    elif mutation == "surface":
        record.surface_code = "other"
    elif mutation == "stream":
        record.stream_code = "intraday"
    elif mutation == "retired":
        record.projection_status = "retired"
        record.retired_at = NOW
        record.retire_reason = "synthetic-retirement"
    elif mutation == "invalid":
        record.record_status = "invalid"
    elif mutation in {"path", "unit", "capability"}:
        setattr(metric, {"path": "field_path", "unit": "unit",
                         "capability": "capability_code"}[mutation], "wrong")
    else:
        seed(database, days=1, extra={"recordId": "other-record", "moderateIntensityMinutes": 99,
                                     "vigorousIntensityMinutes": 99})
        if mutation == "metricless_collision":
            other = session.query(GarminSourceRecord).filter(
                GarminSourceRecord.id != record.id).one()
            session.query(GarminRecordMetric).filter_by(record_id=other.id).delete()
    session.commit()
    assert read(database, source)["rows"][0]["total"] is None


def test_saved_v3_replay_produces_history_and_converges(database, monkeypatch):
    def old_normalizer(*args, **kwargs):
        result = normalize_garmin_payload(*args, **kwargs)
        return replace(result, contract_version="r02-garmin-normalization-contract-v3",
            records=tuple(replace(record, metrics=tuple(metric for metric in record.metrics
                if metric.capability_code != "intensity_minutes")) for record in result.records))
    with monkeypatch.context() as old:
        old.setattr("test_garmin_completed_steps.normalize_garmin_payload", old_normalizer)
        source = seed(database, days=2)
    assert read(database, source)["weeks"][0]["total"] is None
    database[2].rollback()
    settings = Settings(data_dir=database[0].root)
    report = run_garmin_reprocess(settings, start=MONDAY, end=MONDAY + timedelta(days=1),
                                  streams=["daily_summary"])
    assert report.status == "succeeded" and report.processed_count == 2
    assert report.as_dict()["reprocess"]["provider_requests"] == 0
    database[2].expire_all()
    assert read(database, source)["weeks"][0]["total"] == 40
    assert read(database, source)["weeks"][0]["goal"] == 150
    database[2].rollback()
    again = run_garmin_reprocess(settings, start=MONDAY, end=MONDAY + timedelta(days=1),
                                streams=["daily_summary"])
    assert again.processed_count == 0


@pytest.mark.parametrize("days", [0, 2, 4])
def test_overview_current_week_and_statistics_routes(database, monkeypatch, days):
    class FrozenDatetime(type(NOW)):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)
    monkeypatch.setattr("healthcheck.web.pages.datetime", FrozenDatetime)
    source = seed(database, days=days) if days else None
    app, _ = create_ui_app(Settings(data_dir=database[0].root))
    app.state.engine = database[1]
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        # Historical Overview selection must not relabel its current-week card.
        overview = client.get("/brief", params={"start_date": "2099-01-01",
            "end_date": "2099-01-07", "period_at": NOW.isoformat(),
            "garmin_source_id": source or ""})
        assert overview.status_code == 200, overview.text
        card = overview.text.split('<div data-overview-intensity>', 1)[1].split('</div>', 1)[0]
        assert "Минуты интенсивности · Garmin" in card and "за эту неделю" in card
        assert "По правилу Garmin: активные минуты + 2 × интенсивные" in card
        if days == 4:
            assert '<strong>80</strong> из 150' in card
        elif days:
            assert '<strong class="owner-value-low">≥ 40</strong>' in card
            assert 'data-coverage-qualifier="2/4"' in card
            assert "2 из 4 дней" in card
        else:
            assert "нет данных" in card and "<strong>0</strong>" not in card
        for period in ("7", "30"):
            response = client.get("/statistics", params={"period": period,
                "end_date": "2099-01-08", "garmin_source_id": source or ""})
            assert response.status_code == 200, response.text
            section = response.text.split('data-statistics-intensity', 1)[1]
            section = section.split('</section>', 1)[0]
            assert "Минуты интенсивности · Garmin" in section
            assert '<details' in section and '<caption>' in section and 'scope="col"' in section
            assert "нет данных" in section
            missing = section.split('data-intensity-date="2099-01-04"', 1)[1].split('</tr>', 1)[0]
            assert missing.count('<td>нет данных</td>') == 4 and '<td>0</td>' not in missing


def test_templates_escape_source_and_evidence_strings(database):
    packet = read(database, '<script>alert("source")</script>')
    template = statistics_templates.env.get_template("statistics_intensity.html")
    html = template.render(intensity=packet)
    assert '<script>' not in html and '&lt;script&gt;' in html
    template = statistics_templates.env.get_template("overview_intensity.html")
    html = template.render(overview={"intensity": packet})
    assert '<script>' not in html and '&lt;script&gt;' in html


def test_fractional_minutes_remain_visible(database):
    source = seed(database, days=1, extra={"moderateIntensityMinutes": 0.25,
        "vigorousIntensityMinutes": 0.125, "intensityMinutesGoal": 150.5})
    week = read(database, source, end=MONDAY)["weeks"][0]
    assert week["total"] == Decimal("0.5")
    assert week["display"] == {"moderate": "0.25", "vigorous": "0.125",
                               "total": "0.5", "goal": "150.5"}


def test_zero_minutes_and_goal_render_as_values_beside_missing_days(database):
    source = seed(database, days=1, extra=dict.fromkeys((leaf for _, leaf in FIELDS.values()), 0))
    packet = read(database, source, end=MONDAY + timedelta(days=1))
    html = statistics_templates.env.get_template("statistics_intensity.html").render(
        intensity=packet)
    zero = html.split(f'data-intensity-date="{MONDAY}"', 1)[1].split('</tr>', 1)[0]
    assert zero.count('<td>0</td>') == 4
    missing = html.split(f'data-intensity-date="{MONDAY + timedelta(days=1)}"', 1)[1]
    assert missing.split('</tr>', 1)[0].count('<td>нет данных</td>') == 4
    html = statistics_templates.env.get_template("overview_intensity.html").render(
        overview={"intensity": read(database, source, end=MONDAY)})
    assert '<strong>0</strong> из 0' in html


@pytest.mark.parametrize('goal', [None, 0, 150])
def test_statistics_progress_preserves_goal_and_partial_coverage(database, goal):
    source = seed(database, days=2, extra={
        'moderateIntensityMinutes': 10, 'vigorousIntensityMinutes': 5,
        'intensityMinutesGoal': goal,
    })
    packet = read(database, source)
    html = statistics_templates.env.get_template('statistics_intensity.html').render(
        intensity=packet)
    doc = parse_overview(html)
    row = doc.one('tr', **{'data-intensity-week': str(MONDAY)})
    assert '2 из 7' in row.text and '≥ 40' in row.text
    progress = row.find('progress')
    if goal:
        assert len(progress) == 1
        assert Decimal(progress[0].attrs['value']) == 40
        assert Decimal(progress[0].attrs['max']) == 150
        assert '2 из 7' in progress[0].attrs['aria-label']
    else:
        assert not progress
        assert row.find('td')[0].text.strip() == '—'
