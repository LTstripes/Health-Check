"""Focused #343 B2 regressions for the primary source sleep timeline."""

from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import event, select

from healthcheck.analytics.sleep_source_view import read_source_sleep_range
from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import GoogleSleepRecord, GoogleSourceRecord
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.web.sleep_timeline import (
    SLEEP_TIMELINE_DEFAULT_DAYS,
    build_sleep_timeline,
    sleep_timeline_days,
    sleep_timeline_technical,
    timeline_freshness_items,
    timeline_point_note,
)
from test_garmin_query_dashboard import _ui
from test_sleep_metrics import (
    GARMIN_SLEEP_FIXTURE,
    _google_sleep_payload,
    _persist_google,
)
from test_sleep_owner_ui import client_for

END = date(2099, 1, 7)


def _range_point(day: str, **overrides):
    point = {
        "wake_date": day,
        "state": "value",
        "value": 28800,
        "unit": "seconds",
        "record_id": f"rec-{day}",
        "reason": None,
        "is_zero": False,
        "partial": False,
        "role_uncertain": False,
        "candidate_record_ids": [f"rec-{day}"],
        "exclusions": [],
    }
    point.update(overrides)
    return point


def _range_series(provider: str, source_id: str, points):
    google = provider == "google"
    return {
        "source": {
            "source_id": source_id,
            "source_kind": "data_source",
            "source_instance_id": f"users/me/dataSources/{source_id}",
            "device_attributed": google,
            "device_code": None,
            "device_model": "Synthetic Watch" if google else None,
            "device_manufacturer": "Fitbit" if google else None,
            "platform": "fitbit" if google else None,
            "data_source_name": None,
        },
        "points": points,
    }


def _range_packet(series, *, state: str = "records", **overrides):
    packet = {
        "state": state,
        "days": [],
        "series": series,
        "observed_dates": [],
        "missing_dates": [],
        "wake_date_missing_count": 0,
        "wake_date_missing_by_source": {},
        "limit": 400,
    }
    packet.update(overrides)
    return packet


def _seed_nights(paths):
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            for day, seconds, score in ((2, 28800, 82), (3, 27000, 70), (5, 32400, 91)):
                payload = json.loads(GARMIN_SLEEP_FIXTURE.read_text(encoding="utf-8"))
                payload["device"] = {"attributed": False}
                dto = payload["payload"]["dailySleepDTO"]
                dto["calendarDate"] = f"2099-01-{day:02d}"
                dto["sleepTimeSeconds"] = seconds
                dto["sleepScores"]["overall"]["value"] = score
                GarminPersistenceRepository(
                    session,
                    payload_store=ContentAddressedGarminPayloadStore(
                        paths.root / "garmin-artifacts"
                    ),
                ).persist_result(
                    normalize_garmin_payload(payload), payload=json.dumps(payload).encode()
                )
            for day, name, minutes in (
                (2, "first", "410"), (4, "first", "410"), (4, "second", "410"),
                (6, "zero", "0"), (7, "last", "300"),
            ):
                payload = _google_sleep_payload(name=f"synthetic-{day}-{name}")
                wake = date(2099, 1, day)
                previous = wake - timedelta(days=1)
                interval = payload["dataPoints"][0]["sleep"]["interval"]
                interval["startTime"] = f"{previous.isoformat()}T22:00:00Z"
                interval["endTime"] = f"{wake.isoformat()}T05:00:00Z"
                interval["civilStartTime"]["date"] = wake.isoformat()
                interval["civilEndTime"]["date"] = wake.isoformat()
                payload["dataPoints"][0]["sleep"]["summary"]["minutesAsleep"] = minutes
                _persist_google(session, paths, payload=payload)
    finally:
        engine.dispose()


def _timeline_json(page_text: str):
    marker = '<script id="sleep-timeline-data" type="application/json">'
    assert marker in page_text
    return json.loads(page_text.split(marker, 1)[1].split("</script>", 1)[0])


def test_sleep_timeline_window_accepts_only_7_30_and_defaults_30():
    assert sleep_timeline_days(None) == SLEEP_TIMELINE_DEFAULT_DAYS
    assert sleep_timeline_days("7") == 7
    assert sleep_timeline_days("30") == 30
    assert sleep_timeline_days("14") == 30
    assert sleep_timeline_days("nope") == 30


def test_timeline_point_note_keeps_states_distinct():
    assert "явный ноль" in timeline_point_note(
        {"state": "value", "is_zero": True, "partial": False}
    )
    assert "неполная" in timeline_point_note(
        {"state": "value", "is_zero": False, "partial": True}
    )
    assert timeline_point_note(
        {"state": "value", "is_zero": False, "partial": False}
    ) == ""
    assert "Нет сохранённой записи" in timeline_point_note({"state": "no_records"})
    assert "единое значение не выбрано" in timeline_point_note(
        {"state": "ambiguous"}
    )
    assert timeline_point_note(
        {"state": "missing", "reason": "metric_missing"}
    ) == "За эту дату нет пригодного значения."


def test_build_timeline_keeps_gaps_ambiguity_zero_and_labels():
    series = [
        _range_series(
            "garmin",
            "garmin-1",
            [
                _range_point("2099-01-01"),
                _range_point("2099-01-03", value=0, is_zero=True),
                _range_point(
                    "2099-01-04",
                    state="ambiguous",
                    value=None,
                    record_id=None,
                    candidate_record_ids=["a", "b"],
                    reason="ambiguous_garmin_main",
                ),
            ],
        ),
        _range_series("google", "google-1", [_range_point("2099-01-02", value=18000)]),
        _range_series("google", "google-2", [_range_point("2099-01-02", value=19800)]),
    ]
    timeline = build_sleep_timeline(
        {"garmin": _range_packet(series[:1]), "google": _range_packet(series[1:])},
        days=7,
        end_date=END,
        freshness=None,
    )
    assert timeline["dates"][0] == "2099-01-01" and timeline["dates"][-1] == "2099-01-07"
    garmin = timeline["series"][0]
    assert [point["state"] for point in garmin["points"]] == [
        "value", "no_records", "value", "ambiguous", "no_records", "no_records",
        "no_records",
    ]
    assert garmin["points"][0]["value_hours"] == 8.0
    assert garmin["points"][2]["value_seconds"] == 0
    assert garmin["points"][2]["is_zero"] is True
    assert "явный ноль" in garmin["points"][2]["note"]
    ambiguous = garmin["points"][3]
    assert ambiguous["candidate_count"] == 2
    assert ambiguous["record_id"] is None and ambiguous["value_seconds"] is None
    assert "единое значение не выбрано" in ambiguous["note"]
    assert garmin["points"][1]["note"] == "Нет сохранённой записи за эту дату."
    google = timeline["series"][1:]
    assert google[0]["label"].endswith(" · источник 1")
    assert google[1]["label"].endswith(" · источник 2")
    assert google[0]["label"].rsplit(" · источник", 1)[0] == google[1]["label"].rsplit(
        " · источник", 1
    )[0]
    assert timeline["table_rows"][2]["cells"][0]["value_seconds"] == 0
    assert len(timeline["table_rows"]) == 7
    assert timeline["read_limit_exceeded"] is False
    assert timeline["undated_records"] == []


def test_build_timeline_undated_only_records_never_read_confirmed_empty():
    packet = _range_packet(
        [],
        state="records",
        wake_date_missing_count=2,
        wake_date_missing_by_source={"g-1": 2},
    )
    timeline = build_sleep_timeline(
        {"garmin": packet, "google": _range_packet([])}, days=7, end_date=END
    )
    # B1 retained undated rows keep no invented plot series and no empty claim.
    assert timeline["series"] == []
    assert timeline["undated_records"] == [
        {"provider": "garmin", "provider_label": "Garmin", "count": 2}
    ]
    technical = sleep_timeline_technical(timeline)
    assert technical["providers"]["garmin"]["wake_date_missing_by_source"] == {"g-1": 2}
    assert technical["nights"] == []
    assert technical["undated_records"] == timeline["undated_records"]


def test_build_timeline_read_limit_fails_closed_without_counts():
    limited = {
        "state": "read_limit_exceeded",
        "days": [],
        "series": [],
        "observed_dates": None,
        "missing_dates": None,
        "wake_date_missing_count": None,
        "limit": 400,
    }
    timeline = build_sleep_timeline(
        {"garmin": limited, "google": limited}, days=7, end_date=END
    )
    assert timeline["read_limit_exceeded"] is True
    assert timeline["series"] == []
    assert timeline["undated_records"] == []
    assert timeline["providers"]["garmin"]["observed_dates"] is None
    assert timeline["providers"]["google"]["read_limit_exceeded"] is True


def test_timeline_freshness_is_compact_and_separate():
    freshness = {
        "owner": {
            "actionable_items": [
                {"scope_key": "garmin:sleep", "state": "stale", "reason_code": "refresh_overdue"}
            ]
        },
        "not_requested_required": [
            {"scope_key": "google:sleep", "state": "not_requested", "reason_code": "not_requested"}
        ],
        "optional_details": [],
    }
    items = timeline_freshness_items(freshness)
    assert items[0]["provider_label"] == "Garmin" and items[0]["attention"] is True
    assert items[0]["state_text"] == "данные обновлений устарели"
    assert items[0]["reason_text"] == "обновление задерживается"
    assert items[1]["provider_label"] == "Google" and items[1]["attention"] is True
    assert items[1]["state_text"] == "сбор не запрашивался"
    quiet = timeline_freshness_items(
        {"owner": {"actionable_items": []}, "not_requested_required": [], "optional_details": []}
    )
    assert [item["attention"] for item in quiet] == [False, False]
    assert timeline_freshness_items(None) is None


def test_sleep_timeline_technical_counts_states_without_packets():
    timeline = build_sleep_timeline(
        {"garmin": _range_packet([_range_series("garmin", "g-1", [_range_point("2099-01-07")])])},
        days=7,
        end_date=END,
    )
    technical = sleep_timeline_technical(timeline)
    assert technical["window"] == {
        "days": 7, "start_date": "2099-01-01", "end_date": "2099-01-07"
    }
    assert technical["series"][0]["source"]["source_id"] == "g-1"
    assert technical["series"][0]["point_states"] == {"value": 1, "no_records": 6}
    assert technical["series"][0]["points"][-1]["state"] == "value"
    assert technical["nights"] == []
    assert technical["undated_records"] == []


def test_sleep_timeline_technical_discloses_session_and_point_evidence():
    night = {
        "provider": "google",
        "wake_date": "2099-01-07",
        "state": "records",
        "limit": 200,
        "sources": [
            {
                "source": {
                    "source_id": "g-1",
                    "source_kind": "data_source",
                    "source_instance_id": "users/me/dataSources/g-1",
                    "device_attributed": True,
                    "device_code": None,
                    "device_model": "Watch",
                    "device_manufacturer": "Fitbit",
                    "platform": "fitbit",
                    "data_source_name": None,
                },
                "sessions": [
                    {
                        "record_id": "rec-1",
                        "record_status": "partial",
                        "reason": None,
                        "role": {"selection": "single_uncertain_session", "reason": None},
                        "field_states": {"session": "value"},
                        "temporal_evidence": {
                            "precision": "instant",
                            "source_local_date": "2099-01-07",
                            "source_timestamp_utc": "2099-01-07T05:00:00Z",
                            "source_local_timestamp": "2099-01-07T08:00:00",
                            "local_wall_time": None,
                            "source_utc_offset_minutes": 180,
                            "source_timezone": "Europe/Moscow",
                        },
                        "metrics": {
                            "sleep_duration_asleep_seconds": {
                                "state": "value", "eligible": True, "value": 24600,
                                "reason": None, "is_zero": False,
                                "evidence": {"nested": "payload-shape"},
                            },
                            "sleep_score": {
                                "state": "missing", "eligible": False, "value": None,
                                "reason": "metric_missing",
                            },
                        },
                    }
                ],
                "ambiguous": False,
                "summary": None,
            }
        ],
    }
    series = _range_series(
        "google",
        "g-1",
        [
            _range_point(
                "2099-01-07",
                state="ambiguous",
                value=None,
                record_id=None,
                candidate_record_ids=["rec-1", "rec-2"],
                reason="ambiguous_google_main",
                exclusions=[
                    {"record_id": "rec-3", "reason": "google_explicit_main_preferred"}
                ],
            )
        ],
    )
    timeline = build_sleep_timeline(
        {"google": _range_packet([series], days=[night])}, days=7, end_date=END
    )
    technical = sleep_timeline_technical(timeline)
    assert len(technical["nights"]) == 1
    disclosed = technical["nights"][0]
    assert disclosed["provider"] == "google" and disclosed["wake_date"] == "2099-01-07"
    session = disclosed["sources"][0]["sessions"][0]
    assert session["record_id"] == "rec-1"
    assert session["record_status"] == "partial"
    assert session["role"] == {"selection": "single_uncertain_session", "reason": None}
    assert session["temporal_evidence"]["source_utc_offset_minutes"] == 180
    assert session["temporal_evidence"]["source_local_timestamp"] == "2099-01-07T08:00:00"
    assert session["temporal_evidence"]["source_timezone"] == "Europe/Moscow"
    duration = session["metrics"]["sleep_duration_asleep_seconds"]
    assert duration == {
        "state": "value", "eligible": True, "value": 24600, "reason": None, "is_zero": False
    }
    assert "evidence" not in duration  # bounded: no nested raw evidence
    assert session["metrics"]["sleep_score"]["eligible"] is False
    point = technical["series"][0]["points"][-1]
    assert point["reason"] == "ambiguous_google_main"
    assert point["candidate_record_ids"] == ["rec-1", "rec-2"]
    assert point["exclusions"] == [
        {"record_id": "rec-3", "reason": "google_explicit_main_preferred"}
    ]
    assert point["exclusion_reasons"] == ["google_explicit_main_preferred"]


def test_sleep_default_route_is_timeline_with_embedded_packets(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    _seed_nights(paths)
    app.state.engine = create_sqlite_engine(paths)
    statements: list[str] = []
    with client_for(app) as client:
        event.listen(
            app.state.engine,
            "before_cursor_execute",
            lambda _c, _cur, sql, *_a: statements.append(sql),
        )
        page = client.get("/sleep?wake_date=2099-01-07")
        assert page.status_code == 200
        primary, technical = page.text.split(
            '<details class="card owner-details sleep-technical"', 1
        )
        assert 'aria-current="page">Динамика</a>' in page.text
        assert "data-sleep-timeline" in primary
        assert primary.count('data-sleep-series-toggle="') == 2
        assert "График требует JavaScript" in primary
        # All 30 default-window dates render in the accessible table for both exact sources.
        assert primary.count("data-sleep-timeline-cell=") == 60
        assert "8 ч 0 мин" in primary and "7 ч 30 мин" in primary
        assert "явный ноль" in primary
        assert "Несколько записей; значение не выбрано" in primary
        # Garmin native score never becomes ordinary primary copy.
        assert "82 баллы" not in primary
        # Compact freshness stays separate from saved history.
        assert "состояние обновлений неизвестно" in primary
        assert 'href="/imports#data-status"' in primary
        assert "Свежесть обновления отделена от сохранённой истории" in primary
        assert "read_limit_exceeded" not in primary
        assert "result_hash" not in primary
        payload = _timeline_json(page.text)
        assert payload["contract_version"] == "sleep-timeline-ui-v1"
        assert payload["days"] == 30 and payload["end_date"] == "2099-01-07"
        garmin_days = payload["nights"]["garmin"]
        assert len(garmin_days) == 30
        assert {day for day, night in garmin_days.items() if night["sources"]} == {
            "2099-01-02", "2099-01-03", "2099-01-05",
        }
        session = garmin_days["2099-01-02"]["sources"][0]["sessions"][0]
        assert session["metrics"]["sleep_duration_asleep_seconds"]["value"] == 28800
        assert session["metrics"]["sleep_score"]["value"] == 82
        google_series = payload["series"][1]

        def google_point(day):
            return next(
                point for point in google_series["points"] if point["wake_date"] == day
            )

        ambiguous_point = google_point("2099-01-04")
        assert ambiguous_point["state"] == "ambiguous"
        assert ambiguous_point["candidate_count"] == 2
        assert ambiguous_point["candidate_record_ids"]
        assert ambiguous_point["exclusions"] == []
        zero_point = google_point("2099-01-06")
        assert zero_point["state"] == "value" and zero_point["is_zero"] is True
        assert session["record_status"]
        assert session["temporal_evidence"]["source_local_date"] == "2099-01-02"
        assert '"point_states"' in technical
        assert '"read_limit_exceeded": false' in technical
        assert '"sleep_score"' in technical
        assert '"record_status"' in technical
        assert '"temporal_evidence"' in technical
        assert '"exclusions"' in technical
    assert "BEGIN" in statements
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )


def test_sleep_timeline_windows_and_legacy_views_stay_available(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    _seed_nights(paths)
    app.state.engine = create_sqlite_engine(paths)
    with client_for(app) as client:
        week = client.get("/sleep?wake_date=2099-01-07&days=7")
        assert week.status_code == 200
        assert 'aria-current="true" href="/sleep?view=timeline&amp;days=7' in week.text
        assert week.text.count("data-sleep-timeline-cell=") == 14
        invalid = client.get("/sleep?wake_date=2099-01-07&days=14")
        assert invalid.status_code == 200
        assert invalid.text.count("data-sleep-timeline-cell=") == 60
        assert "data-sleep-timeline" in client.get("/sleep?view=timeline&wake_date=2099-01-07").text
        assert "Выбранная ночь" in client.get(
            "/sleep?view=garmin&wake_date=2099-01-07"
        ).text
        assert "Google · выбранная ночь" in client.get(
            "/sleep?view=google&wake_date=2099-01-07"
        ).text
        assert "Сравнение сна" in client.get("/sleep?view=compare&wake_date=2099-01-07").text
        assert client.get("/agreement").status_code == 200
        assert client.get("/sleep?view=invalid&wake_date=2099-01-07").status_code == 200


def test_sleep_timeline_undated_only_provider_is_unknown_not_confirmed_empty(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            _persist_google(session, paths, payload=_google_sleep_payload())
            record = session.scalar(select(GoogleSourceRecord))
            record.source_local_date = date(2099, 1, 7)
            session.scalar(select(GoogleSleepRecord)).wake_date = None
    finally:
        engine.dispose()
    app.state.engine = create_sqlite_engine(paths)
    with client_for(app) as client:
        page = client.get("/sleep?wake_date=2099-01-07")
        primary, technical = page.text.split(
            '<details class="card owner-details sleep-technical"', 1
        )
        assert page.status_code == 200
        assert 'data-owner-state="unknown"' in primary
        assert "пригодной даты пробуждения" in primary
        assert "Google — 1" in primary
        assert "нет текущих сохранённых ночей" not in primary
        assert 'data-owner-state="confirmed_empty"' not in primary
        assert '"wake_date_missing_by_source"' in technical
        assert "wake_date_missing_by_source" not in primary


def test_sleep_timeline_true_empty_stays_confirmed_empty(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with client_for(app) as client:
        page = client.get("/sleep?wake_date=2099-01-07")
        primary = page.text.split('<details class="card owner-details sleep-technical"', 1)[0]
        assert page.status_code == 200
        assert 'data-owner-state="confirmed_empty"' in primary
        assert "нет текущих сохранённых ночей" in primary
        assert "пригодной даты пробуждения" not in primary


def test_sleep_timeline_read_limit_and_unavailable_stay_honest(tmp_path, monkeypatch):
    app, _settings, paths = _ui(tmp_path)
    _seed_nights(paths)
    app.state.engine = create_sqlite_engine(paths)
    monkeypatch.setattr(
        "healthcheck.analytics.sleep_source_view.MAX_SOURCE_SLEEP_RANGE_RECORDS", 0
    )
    with client_for(app) as client:
        page = client.get("/sleep?wake_date=2099-01-07")
        primary, technical = page.text.split(
            '<details class="card owner-details sleep-technical"', 1
        )
        assert page.status_code == 200
        assert "слишком много сохранённых записей" in primary
        assert "data-sleep-series-toggle" not in primary
        assert '"read_limit_exceeded": true' in technical
    monkeypatch.undo()
    app.state.engine.dispose()
    paths.database.unlink()
    with client_for(app) as client:
        page = client.get("/sleep?wake_date=2099-01-07")
        assert page.status_code == 200
        assert "Локальное хранилище данных не готово" in page.text
        assert "Состояние свежести источников недоступно" in page.text


def test_week_range_matches_accepted_reader_without_writes(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    _seed_nights(paths)
    engine = create_sqlite_engine(paths)
    direct: dict[str, object] = {}
    try:
        with session_scope(engine) as session:
            for provider in ("garmin", "google"):
                direct[provider] = read_source_sleep_range(
                    session, provider=provider, wake_date=END, days=7
                )
    finally:
        engine.dispose()
    app.state.engine = create_sqlite_engine(paths)
    with client_for(app) as client:
        payload = _timeline_json(client.get("/sleep?wake_date=2099-01-07&days=7").text)
    for provider, packet in direct.items():
        referenced = {
            point["record_id"]
            for series in packet["series"]
            for point in series["points"]
            if point["record_id"]
        }
        embedded = {
            session["record_id"]
            for day in payload["nights"][provider].values()
            for source in day["sources"]
            for session in source["sessions"]
        }
        assert referenced <= embedded
