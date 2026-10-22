"""Saved packet → exact strings / bounded geometry / accessible compact markup."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from healthcheck.garmin.completed_steps_read import CompletedStepsDay, CompletedStepsWindow
from healthcheck.garmin.observed_steps_read import StepsSourceIdentity
from healthcheck.garmin.steps_statistics import summarize_completed_days
from healthcheck.web.owner_presentation import owner_date
from healthcheck.web.steps_presentation import garmin_steps_view, google_steps_view
from test_google_steps_summary import packet


def garmin_packet(*values):
    start = date(2099, 1, 1)
    identity = StepsSourceIdentity("garmin-one", "garmin", "account", "synthetic")
    return CompletedStepsWindow(
        source_id=identity.source_id, start_date=start, end_date=start + timedelta(days=6),
        evaluated_at=datetime(2099, 2, 1, tzinfo=UTC), source_identity=identity,
        source_choices=(identity,), search_complete=True, candidates_examined=len(values),
        provenance_examined=len(values), artifacts_examined=len(values), bytes_examined=0,
        cells=tuple(CompletedStepsDay(
            identity.source_id, start + timedelta(days=i), datetime(2099, 2, 1, tzinfo=UTC),
            "value" if value is not None else "unavailable", value,
        ) for i, value in enumerate((*values, *([None] * (7 - len(values)))))),
    )


@pytest.mark.parametrize("factory", [packet, garmin_packet])
@pytest.mark.parametrize("values,total,mean,count", [
    ((17, 0, None, 3), "20", "6.7", 3),
    ((0, 0, 0), "0", "0.0", 3),
    ((None, None), None, None, 0),
    ((9223372036854775807, 9223372036854775807, 0), "18446744073709551614",
     "6148914691236517204.7", 3),
])
def test_exact_counts_denominator_and_safe_geometry(factory, values, total, mean, count):
    original = factory(*values)
    before = deepcopy(original)
    view = (google_steps_view if factory is packet else garmin_steps_view)(original)
    assert original == before
    assert view["assessed"] and (view["total"], view["mean"], view["count"]) == (total, mean, count)
    assert view["days"] == 7
    for row in view["rows"]:
        assert type(row["x"]) is int and 20 <= row["x"] <= 880
        assert row["y"] is None or type(row["y"]) is int and 20 <= row["y"] <= 150
        assert row["value"] is None or type(row["value"]) is str
    # A missing day breaks the polyline, rather than interpolating an invented zero.
    for segment in view["segments"]:
        left = next(row for row in view["rows"] if row["x"] == segment["x1"])
        right = next(row for row in view["rows"] if row["x"] == segment["x2"])
        assert right["index"] - left["index"] == 1
        assert left["value"] is not None and right["value"] is not None
    if total == "0":
        assert all(row["y"] == 150 for row in view["rows"] if row["value"] is not None)


@pytest.mark.parametrize("reason", ["source_selection_required", "source_not_found"])
def test_garmin_selection_and_incomplete_packets_never_expose_prefix(reason):
    for original in [replace(garmin_packet(17), reason=reason),
                     replace(garmin_packet(17), search_complete=False)]:
        view = garmin_steps_view(original)
        assert not view["assessed"] and view["total"] is view["count"] is None
        assert view["rows"] == []


def test_garmin_complete_window_reuses_existing_statistics_without_new_read():
    original = garmin_packet(17, 0, None, 3)
    summary = summarize_completed_days(original)
    view = garmin_steps_view(original)
    assert view["total"] == str(summary.total) == "20"
    assert view["count"] == summary.eligible_day_count == 3
    assert summary.unobserved_day_count == 0
    assert view["days"] == summary.calendar_day_count == 7
    assert view["start"] == original.start_date and view["end"] == original.end_date


def test_garmin_missing_completed_cell_is_not_a_trusted_prefix():
    original = garmin_packet(17, 0)
    assert not garmin_steps_view(replace(original, cells=original.cells[:-1]))["assessed"]
    # Today/future dates really omitted by the reader do not become zero.
    original = replace(original, evaluated_at=datetime(2099, 1, 3, tzinfo=UTC),
                       cells=original.cells[:2])
    view = garmin_steps_view(original)
    assert view["assessed"] and view["total"] == "17" and view["count"] == 2
    assert view["days"] == 7 and len(view["rows"]) == 2


@pytest.mark.parametrize("damage", ["incomplete", "duplicate", "invalid", "identity"])
def test_google_unassessed_adapter_cannot_draw_a_prefix(damage):
    original = packet(17, 0)
    if damage == "incomplete":
        original["search_complete"] = False
    elif damage == "duplicate":
        original["cells"][1]["calendar_date"] = original["cells"][0]["calendar_date"]
    elif damage == "invalid":
        original["cells"][0]["value"] = True
    else:
        original["source_identity"]["source_id"] = "other"
    view = google_steps_view(original)
    assert not view["assessed"] and view["total"] is view["count"] is None
    assert view["rows"] == []


def test_google_full_observed_grid_still_discloses_unknown_coverage_and_exact_strings():
    original = packet(*([9223372036854775807] * 7))
    view = google_steps_view(original)
    directory = Path(__file__).parents[1] / "src/healthcheck/web/templates"
    env = Environment(loader=FileSystemLoader(directory), autoescape=select_autoescape())
    env.filters["owner_date"] = owner_date
    html = env.get_template("statistics_steps_chart.html").render(view=view)
    assert "7 из 7 дней с данными" in html and "полнота суток не подтверждена" in html
    assert "64563604257983430649" in html
    assert '<details class="owner-info">' in html and "Точное среднее" in html
    assert "<noscript>" in html
    payload = html.split('data-steps-chart-data>', 1)[1].split("</script>", 1)[0]
    assert all(row["value"] == "9223372036854775807" for row in json.loads(payload))


def test_no_javascript_count_arithmetic_or_date_timezone_conversion():
    source = (Path(__file__).parents[1]
              / "src/healthcheck/web/static/statistics_steps.js").read_text(encoding="utf-8")
    assert "parseInt" not in source and "Number(" not in source and "new Date" not in source
    assert 'row.value === null' in source and "textContent" in source
