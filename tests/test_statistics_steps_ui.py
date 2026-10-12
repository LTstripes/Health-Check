"""Real Statistics route over synthetic materialized Steps, never Owner/provider data."""

import json
import os
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.garmin.observed_steps import SavedDailyStepsRepository
from healthcheck.garmin.observed_steps_read import read_observed_steps_window
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.web.owner_presentation import owner_date
from test_garmin_observed_steps import (
    ABSENT,
    DAY,
    duplicate_candidates,
    duplicate_provenance,
    materialize,
    source,
)
from test_statistics_ui import projection_database as projection_database
from test_statistics_ui import statistics_ui as statistics_ui

END = DAY + timedelta(days=8)


class StepsParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.states, self.values = {}, {}
        self.day = None
        self.in_value = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "data-steps-date" in attrs:
            self.day = attrs["data-steps-date"]
            self.states[self.day] = attrs["data-steps-state"]
            self.values[self.day] = ""
        if tag == "td" and attrs.get("class") == "statistics-steps-value":
            self.in_value = True

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_value = False
        if tag == "tr":
            self.day = None

    def handle_data(self, text):
        if self.day and self.in_value:
            self.values[self.day] += text


def steps_html(response):
    return response.text.split('<section class="statistics-steps"', 1)[1].split("</section>", 1)[0]


def export(response, name):
    root = os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR")
    if root:
        directory = Path(root)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"steps-{name}.html").write_text(response.text, encoding="utf-8")


def seed_steps(session, paths):
    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    counts = [17, 0, None, ABSENT, True, 7, None]
    for index, count in enumerate(counts):
        saved, _ = materialize(session, store, DAY + timedelta(days=index), count)
    materialize(session, store, DAY + timedelta(days=5), 9)
    materialize(session, store, DAY + timedelta(days=6), ABSENT)
    materialize(session, store, END, 2**53 + 1)
    other, _ = materialize(session, store, END, 999, source("second-synthetic-account"))
    session.commit()
    return saved.source.id, other.source.id


@pytest.mark.parametrize("period", ["7", "30", "calendar_year", "trailing365", "year_to_date"])
def test_steps_reader_uses_exact_period_and_preserves_result(statistics_ui, monkeypatch, period):
    session, paths, client = statistics_ui
    first, other = seed_steps(session, paths)
    captured = []

    def capture(read_session, **kwargs):
        result = read_observed_steps_window(read_session, **kwargs)
        captured.append((kwargs, result))
        return result

    monkeypatch.setattr("healthcheck.web.statistics.read_observed_steps_window", capture)
    params = {
        "period": period,
        "end_date": str(END),
        "calendar_year": 2099,
        "garmin_source_id": first,
    }
    response = client.get("/statistics", params=params)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    selection, result = captured[0]
    assert selection == {
        "source_id": first,
        "start_date": result.start_date,
        "end_date": result.end_date,
    }
    assert (f"{owner_date(result.start_date)} — {owner_date(result.end_date)}"
            in steps_html(response))
    parser = StepsParser(response.text)
    assert parser.states == {str(cell.calendar_date): cell.state for cell in result.cells}
    assert parser.values == {
        str(cell.calendar_date): str(cell.value) if cell.value is not None else "Недоступно"
        for cell in result.cells
    }
    section = steps_html(response)
    assert "9007199254740993" in section and "9007199254740992" not in section
    assert other not in section
    assert "unknown / unknown / unknown / unknown" in section
    assert "projection_not_run" not in section
    assert "not_evidenced" in section
    assert "statistics-denominator" not in section
    assert "statistics-comparison" not in section
    assert "999" not in parser.values.values()
    for cell in result.cells:
        for evidence in cell.evidence:
            assert evidence.record_id in section
            assert evidence.metric_row_id in section
            assert evidence.raw_payload_id in section
            assert evidence.content_hash in section
            for observation_id in evidence.observation_ids:
                assert observation_id in section
    export(response, f"a-{period}")
    second = client.get("/statistics", params=dict(params, garmin_source_id=other))
    assert StepsParser(second.text).values[str(END)] == "999"
    assert first not in steps_html(second)
    export(second, f"b-{period}")
    unselected = client.get("/statistics", params=dict(params, garmin_source_id=""))
    assert 'data-steps-selection="required"' in unselected.text
    assert not StepsParser(unselected.text).states
    export(unselected, f"unselected-{period}")
    root = os.environ.get("HEALTHCHECK_STATISTICS_FIXTURES_DIR")
    if root:
        (Path(root) / "steps-sources.json").write_text(
            json.dumps({"a": first, "b": other}), encoding="utf-8"
        )
        if period == "year_to_date":
            # All navigation captures must share this exact persisted source pair.
            for choice in ("7", "30", "calendar_year", "trailing365", "year_to_date"):
                for name, selected in (("a", first), ("b", other), ("unselected", "")):
                    rendered = client.get(
                        "/statistics",
                        params=dict(
                            params,
                            period=choice,
                            garmin_source_id=selected,
                        ),
                    )
                    assert rendered.status_code == 200
                    export(rendered, f"{name}-{choice}")
            export(
                client.get(
                    "/statistics",
                    params=dict(
                        params,
                        period="7",
                        end_date="2099-02-08",
                    ),
                ),
                "no-latest",
            )


@pytest.mark.parametrize("sole", [False, True])
def test_steps_no_auto_selection_even_sole_source(statistics_ui, monkeypatch, sole):
    session, paths, client = statistics_ui
    if sole:
        materialize(session, ContentAddressedGarminPayloadStore(paths.root / "artifacts"), count=0)
        session.commit()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Steps reader requires explicit selection")

    monkeypatch.setattr("healthcheck.web.statistics.read_observed_steps_window", forbidden)
    response = client.get("/statistics", params={"end_date": str(END)})
    assert response.status_code == 200
    assert 'data-steps-selection="required"' in response.text
    selector = response.text.split('name="garmin_source_id"', 1)[1].split("</select>", 1)[0]
    assert 'value="" selected' in selector
    assert not StepsParser(response.text).states
    export(response, "sole" if sole else "empty")


@pytest.mark.parametrize("kind", ["candidate", "provenance"])
def test_steps_real_caps_keep_independent_cells(statistics_ui, kind):
    session, paths, client = statistics_ui
    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    saved, _ = materialize(session, store, count=0)
    later, projected = materialize(session, store, DAY + timedelta(days=1), 17)
    if kind == "candidate":
        duplicate_candidates(session, projected, 4097)
    else:
        duplicate_provenance(session, later, 4097)
    session.commit()
    response = client.get(
        "/statistics",
        params={"days": 7, "end_date": "2099-01-08", "garmin_source_id": saved.source.id},
    )
    assert response.status_code == 200
    parser = StepsParser(response.text)
    assert parser.values[str(DAY)] == "0"
    assert parser.states[str(DAY + timedelta(days=1))] == "search_incomplete"
    assert parser.values[str(DAY + timedelta(days=1))] == "Недоступно"
    assert f"{kind}_limit_exceeded" in steps_html(response)
    assert 'role="status"' in steps_html(response)
    assert "не завершён; ссылки могут быть частичными" in steps_html(response)
    export(response, f"cap-{kind}")


def test_steps_ui_never_materializes_or_writes_and_never_seeks_latest(statistics_ui, monkeypatch):
    session, paths, client = statistics_ui
    first, _ = seed_steps(session, paths)
    session.rollback()
    statements = []

    def forbidden(*_args, **_kwargs):
        pytest.fail("UI request attempted Steps materialization")

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())

    monkeypatch.setattr(SavedDailyStepsRepository, "project_day", forbidden)
    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        for _ in range(2):
            response = client.get(
                "/statistics",
                params={"days": 7, "end_date": "2099-02-08", "garmin_source_id": first},
            )
            parser = StepsParser(response.text)
            assert set(parser.states.values()) == {"projection_unavailable"}
            assert set(parser.values.values()) == {"Недоступно"}
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert statements and set(statements) <= {"SELECT", "BEGIN", "PRAGMA"}


def test_steps_reader_failure_uses_existing_html_error_contract(statistics_ui, monkeypatch):
    session, paths, client = statistics_ui
    first, _ = seed_steps(session, paths)

    def fail(*_args, **_kwargs):
        raise SQLAlchemyError("synthetic Steps failure")

    monkeypatch.setattr("healthcheck.web.statistics.read_observed_steps_window", fail)
    response = client.get("/statistics", params={"garmin_source_id": first})
    assert response.status_code == 500 and 'role="alert"' in response.text
    assert "synthetic Steps failure" not in response.text
