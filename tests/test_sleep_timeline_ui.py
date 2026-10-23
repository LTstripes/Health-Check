"""Focused #343 B2 regressions for the primary source sleep timeline."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
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
        assert "Сбой обновления не удаляет сохранённую историю" in primary
        assert '<details class="owner-info sleep-source-status" data-sleep-freshness>' in primary
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


def _seed_normal_google(paths, *, competitor=False, competitor_wake=None):
    from healthcheck.db.models import GoogleSource
    from healthcheck.google.contracts import (
        FAMILY_ALL_SOURCES,
        FAMILY_GOOGLE_WEARABLES,
        GoogleSourceIdentity,
        GoogleSourceKind,
    )
    from test_sleep_source_view import _persist_account_garmin, _persist_identity

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            _persist_account_garmin(session, paths)
            family_id = None
            excluded_id = None
            for instance, kind, family, nap in (
                (FAMILY_GOOGLE_WEARABLES, GoogleSourceKind.FAMILY_AGGREGATE,
                 FAMILY_GOOGLE_WEARABLES, None),
                ("users/me/dataSources/FITBIT-list", GoogleSourceKind.DATA_SOURCE,
                 FAMILY_ALL_SOURCES, None),
                ("users/me/dataSources/old-health-connect-nap", GoogleSourceKind.DATA_SOURCE,
                 None, True),
            ):
                payload = _google_sleep_payload(name=instance)
                payload["dataPoints"][0].pop("dataSource")
                metadata = payload["dataPoints"][0]["sleep"]["metadata"]
                metadata.pop("main", None)
                metadata.pop("nap", None)
                if nap:
                    metadata["nap"] = True
                result = _persist_identity(session, paths, payload, GoogleSourceIdentity(
                    source_kind=kind, source_instance_id=instance,
                    platform="FITBIT" if "FITBIT" in instance else None,
                ), family)
                identity = result.records[0].google_source_id
                if kind == GoogleSourceKind.FAMILY_AGGREGATE:
                    family_id = identity
                elif "FITBIT" in instance:
                    excluded_id = identity
            if competitor:
                payload = _google_sleep_payload(name="competitor")
                if competitor_wake:
                    wake = competitor_wake
                    previous = wake - timedelta(days=1)
                    interval = payload["dataPoints"][0]["sleep"]["interval"]
                    interval["startTime"] = f"{previous}T22:00:00Z"
                    interval["endTime"] = f"{wake}T05:00:00Z"
                    interval["civilStartTime"]["date"] = wake.isoformat()
                    interval["civilEndTime"]["date"] = wake.isoformat()
                _persist_google(session, paths, payload=payload)
            session.flush()
            source = session.get(GoogleSource, excluded_id)
            session.add(GoogleSource(
                provider_id=source.provider_id, acquisition_source_id=source.acquisition_source_id,
                source_kind="data_source", provider_code=source.provider_code,
                source_instance_id="users/me/dataSources/FITBIT-empty",
                platform="FITBIT", device_attributed=False,
                source_contract_version=source.source_contract_version,
            ))
    finally:
        engine.dispose()
    return family_id, excluded_id


def test_normal_google_uses_sole_eligible_family_and_retains_alternates(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    family_id, excluded_id = _seed_normal_google(paths)
    app.state.engine = create_sqlite_engine(paths)
    with client_for(app) as client:
        for days in (7, 30):
            page = client.get(f"/sleep?wake_date=2099-01-02&days={days}")
            assert page.status_code == 200
            timeline = _timeline_json(page.text)
            assert [item["label"] for item in timeline["display_series"]] == ["Garmin", "Google"]
            assert timeline["google_selection"]["status"] == "sole_google_wearables"
            assert timeline["google_selection"]["selected_source_id"] == family_id
            assert len(timeline["series"]) == 4  # all stored Sleep B1 identities
            assert len(timeline["google_selection"]["options"]) == 4  # plus empty metadata
            point = timeline["display_series"][1]["points"][-1]
            assert point["value_seconds"] == 24600
            assert point["role_uncertain"] is True
            assert point["candidate_count"] == 1
            sources = timeline["nights"]["google"]["2099-01-02"]["sources"]
            family = next(item for item in sources if item["source"]["source_id"] == family_id)
            assert family["sessions"][0]["role"]["selection"] == "single_uncertain_session"
            excluded = next(item for item in sources if item["source"]["source_id"] == excluded_id)
            duration = excluded["sessions"][0]["metrics"]["sleep_duration_asleep_seconds"]
            assert duration["eligible"] is False
            assert "google_family_excluded" in page.text
            assert "FITBIT-empty" in page.text
            assert "google_nap_only" in page.text
            assert page.text.count('data-sleep-series-toggle="') == 2


def test_normal_google_requires_choice_for_two_eligible_sources_and_rejects_stale_choice(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    family_id, excluded_id = _seed_normal_google(paths, competitor=True)
    app.state.engine = create_sqlite_engine(paths)
    with client_for(app) as client:
        url = "/sleep?wake_date=2099-01-02&days=7"
        initial = _timeline_json(client.get(url).text)
        assert initial["google_selection"]["status"] == "require_selection"
        assert [item["provider"] for item in initial["display_series"]] == ["garmin"]
        chosen = client.get(url + "&google_sleep_source_id=" + family_id)
        packet = _timeline_json(chosen.text)
        assert packet["google_selection"]["status"] == "explicit"
        assert packet["display_series"][1]["source"]["source_id"] == family_id
        assert packet["series"] == initial["series"]
        assert packet["nights"] == initial["nights"]
        assert "days=30&amp;wake_date=2099-01-02&amp;google_sleep_source_id=" in chosen.text
        for invalid in (excluded_id, "foreign-source", family_id + "-stale"):
            packet = _timeline_json(client.get(url + "&google_sleep_source_id=" + invalid).text)
            assert packet["google_selection"]["status"] == "invalid_selection"
            assert [item["provider"] for item in packet["display_series"]] == ["garmin"]
        # A previously selected source outside the requested window never falls back.
        packet = _timeline_json(client.get(
            "/sleep?wake_date=2099-02-02&days=7&google_sleep_source_id=" + family_id
        ).text)
        assert packet["google_selection"]["status"] == "invalid_selection"
        assert packet["display_series"] == []


def test_normal_google_ambiguity_blocks_default_and_zero_is_eligible():
    family = _range_series("google", "family", [_range_point("2099-01-07", value=0, is_zero=True)])
    family["source"].update(source_kind="family_aggregate",
                            source_instance_id="users/me/dataSourceFamilies/google-wearables")
    ambiguous = _range_series("google", "other", [_range_point(
        "2099-01-07", state="ambiguous", value=None, record_id=None,
        candidate_record_ids=["a", "b"],
    )])
    packet = {"google": _range_packet([family, ambiguous])}
    timeline = build_sleep_timeline(packet, days=7, end_date=END)
    assert timeline["google_selection"]["status"] == "require_selection"
    assert timeline["display_series"] == []
    chosen = build_sleep_timeline(packet, days=7, end_date=END, google_source_id="family")
    assert chosen["display_series"][0]["points"][-1]["is_zero"] is True
    assert chosen["display_series"][0]["points"][-1]["value_seconds"] == 0
    assert packet["google"]["series"][0]["source"]["source_id"] == "family"


def test_auto_google_default_does_not_become_human_choice_when_window_expands(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    family_id, _ = _seed_normal_google(
        paths, competitor=True, competitor_wake=date(2098, 12, 20),
    )
    app.state.engine = create_sqlite_engine(paths)
    with client_for(app) as client:
        week_url = "/sleep?wake_date=2099-01-02&days=7"
        week = client.get(week_url)
        assert _timeline_json(week.text)["google_selection"]["status"] == "sole_google_wearables"
        import re

        preset = re.search(r'href="(/sleep\?view=timeline&amp;days=30[^"]*)"', week.text)[1]
        assert "google_sleep_source_id" not in preset
        month = client.get(preset.replace("&amp;", "&"))
        packet = _timeline_json(month.text)
        assert packet["google_selection"]["status"] == "require_selection"
        assert [item["provider"] for item in packet["display_series"]] == ["garmin"]
        # Only a source the user explicitly picked survives changing the window.
        explicit = client.get(week_url + "&google_sleep_source_id=" + family_id)
        preset = re.search(r'href="(/sleep\?view=timeline&amp;days=30[^"]*)"', explicit.text)[1]
        assert "google_sleep_source_id=" + family_id in preset
        packet = _timeline_json(client.get(preset.replace("&amp;", "&")).text)
        assert packet["google_selection"]["status"] == "explicit"
        assert packet["display_series"][1]["source"]["source_id"] == family_id


def test_google_undated_source_details_retain_presence_without_point_or_selection(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            _persist_google(session, paths, payload=_google_sleep_payload())
            record = session.scalar(select(GoogleSourceRecord))
            source_id = record.google_source_id
            record.source_local_date = date(2099, 1, 7)
            session.scalar(select(GoogleSleepRecord)).wake_date = None
    finally:
        engine.dispose()
    app.state.engine = create_sqlite_engine(paths)
    with client_for(app) as client:
        for days in (7, 30):
            url = f"/sleep?wake_date=2099-01-07&days={days}"
            page = client.get(url)
            assert page.status_code == 200
            packet = _timeline_json(page.text)
            assert packet["providers"]["google"]["wake_date_missing_by_source"][source_id] == 1
            option = next(item for item in packet["google_selection"]["options"]
                          if item["source_id"] == source_id)
            assert option["has_sleep_records"] is True
            assert option["wake_date_missing_count"] == 1
            assert option["value_dates"] == option["ambiguous_dates"] == 0
            assert option["selectable"] is False
            assert packet["series"] == packet["display_series"] == []
            assert packet["google_selection"]["status"] == "no_eligible_series"
            details = (
                page.text.split('data-sleep-alternate-sources', 1)[1].split('</details>', 1)[0])
            assert "Записи без пригодной даты пробуждения: 1; на график не нанесены." in details
            assert "Нет записей сна в этом окне." not in details
            assert f'<option value="{source_id}" disabled>' in details
            selected = _timeline_json(client.get(url + "&google_sleep_source_id=" + source_id).text)
            assert selected["google_selection"]["status"] == "invalid_selection"
            assert selected["display_series"] == []


# #501 uses accepted analysis fixtures as its packet oracle, never a copied formula.
def _regularity_packet(provider="google", count=7, *, days=7, end=date(2026, 10, 8)):
    from copy import deepcopy

    from test_saved_sleep_analysis import sections

    raw = deepcopy(sections(count=count, provider=provider)["sleep"]["providers"][provider][
        "source_range"])
    source = _range_series(provider, "sleep", [])["source"]
    by_date = {day["wake_date"]: day for day in raw["days"]}
    start = end - timedelta(days=days - 1)
    raw.update(provider=provider, contract_version="source-sleep-range-v1",
               start_date=start.isoformat(), end_date=end.isoformat(), limit=400)
    raw["days"] = [by_date.get((start + timedelta(days=i)).isoformat(), {
        "wake_date": (start + timedelta(days=i)).isoformat(), "sources": [],
    }) for i in range(days)]
    for day in raw["days"]:
        for group in day["sources"]:
            group["source"] = deepcopy(source)
    raw["series"] = [_range_series(provider, "sleep", [
        _range_point(day["wake_date"]) for day in raw["days"] if day["sources"]
    ])]
    return raw


def _regularity_view(packet, *, provider="google", days=7, end=date(2026, 10, 8)):
    from healthcheck.web.sleep_regularity import build_sleep_regularity

    series = {**packet["series"][0], "provider": provider, "label": provider.title()}
    return build_sleep_regularity({provider: packet}, [series], days=days, end_date=end,
        google_selection={"selected_source_id": "sleep", "status": "explicit"})


@pytest.mark.parametrize("provider", ["google", "garmin"])
def test_sleep_regularity_reuses_packet_and_omits_providerwide_counts(provider, monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace

    from healthcheck import saved_sleep_analysis as accepted
    from healthcheck.web import sleep_regularity as presenter

    packet = _regularity_packet(provider)
    before = deepcopy(packet)
    captured = []
    original = presenter.analyze_saved_sleep
    def capture(sections, request):
        source = sections["sleep"]["providers"][provider]
        assert source["selected_source_id"] == "sleep"
        assert source["acquisition_coverage"] == {"state": "unknown"}
        assert set(source["source_range"]).isdisjoint({
            "observed_dates", "missing_dates", "wake_date_missing_count", "series"})
        assert all("state" not in day for day in source["source_range"]["days"])
        original(sections, request)
        captured.append(sections)
    monkeypatch.setattr(presenter, "analyze_saved_sleep", capture)
    result = _regularity_view(packet, provider=provider)["sources"][0]
    oracle = {"sleep": {"providers": {provider: {
        "selected_source_id": "sleep", "acquisition_coverage": {"state": "unknown"},
        "source_range": deepcopy(packet),
    }}}}
    accepted.analyze_saved_sleep(oracle, SimpleNamespace(include_sleep_regularity=True,
        include_context_recovery=False, sleep_day_types=()))
    expected = oracle["sleep_regularity"]
    assert result["eligible_nights"] == expected["eligible_nights"] == 7
    assert result["min_nights"] == expected["min_nights"]
    assert captured[0]["sleep_regularity"] == expected
    assert captured[0]["sleep_analysis_inputs"]["night_exclusions"] == oracle[
        "sleep_analysis_inputs"]["night_exclusions"]
    for actual, group in zip(result["groups"], expected["groups"], strict=True):
        assert actual["partition"] == group["partition"]
        assert actual["nights"] == group["nights"]
        for endpoint in ("start", "end"):
            assert actual[endpoint]["minutes"] == group["clocks"][endpoint]["circular_sd_minutes"]
    assert packet == before
    assert "record_ids" not in json.dumps(result) and "interval_snapshots" not in json.dumps(result)


@pytest.mark.parametrize("count", [0, 2, 7])
def test_sleep_regularity_insufficient_and_actual_zero_stay_distinct(count):
    packet = _regularity_packet(count=count)
    row = _regularity_view(packet)["sources"][0]
    assert row["eligible_nights"] == count
    if count == 0:
        assert row["groups"] == [] and row["state"] == "insufficient"
    elif count == 2:
        assert row["groups"][0]["start"]["text"] == "Недостаточно ночей"
        assert row["groups"][0]["start"]["minutes"] is None
    else:
        assert row["groups"][0]["start"]["text"] == "0 мин"
        assert row["groups"][0]["start"]["minutes"] == 0


@pytest.mark.parametrize("problem", ["overflow", "missing_day", "mismatched", "malformed"])
def test_sleep_regularity_incomplete_input_never_produces_prefix_or_zero(problem):
    packet = _regularity_packet()
    if problem == "overflow":
        packet["state"] = "read_limit_exceeded"
    elif problem == "missing_day":
        packet["days"].pop()
    elif problem == "mismatched":
        packet["end_date"] = "2026-10-09"
    else:
        packet["days"][0]["sources"][0]["sessions"][0]["metrics"] = {}
    row = _regularity_view(packet)["sources"][0]
    assert row["state"] == "unavailable" and row["groups"] == []
    assert row["eligible_nights"] is None and row["excluded_nights"] is None


def test_sleep_regularity_midnight_dst_offset_methods_and_all_partitions():
    from datetime import datetime

    from test_saved_sleep_analysis import item

    packet = _regularity_packet()
    # Local clocks straddle midnight. A linear-clock SD would be hundreds of minutes.
    for i, (stamp, zone, offset) in enumerate([
        ("2026-10-01T23:30:00Z", "UTC", 0),
        ("2026-10-03T00:00:00Z", "UTC", 0),
        ("2026-10-04T00:30:00Z", "UTC", 0),
    ]):
        night = item({"sleep": {"providers": {"google": {"source_range": packet}}}}, i)
        start = datetime.fromisoformat(stamp)
        end = start + timedelta(hours=7)
        for endpoint, instant in (("start", start), ("end", end)):
            cell = night["metrics"][f"sleep_{endpoint}_at"]
            cell["value"] = instant.isoformat()
            snapshot = cell["evidence"]["interval_snapshots"][0]
            snapshot[f"{endpoint}_at_utc"] = instant.isoformat()
            snapshot[f"{endpoint}_temporal"].update(
                source_timezone=zone, source_utc_offset_minutes=offset)
    # Keep the last four nights in a different accepted method partition.
    for day in packet["days"][3:]:
        day["sources"][0]["sessions"][0]["metrics"]["sleep_start_at"][
            "comparison_basis"] = "other_saved_method"
    row = _regularity_view(packet)["sources"][0]
    assert len(row["groups"]) == 2
    assert sorted(group["nights"] for group in row["groups"]) == [3, 4]
    circular = next(group for group in row["groups"] if group["nights"] == 3)
    assert circular["start"]["minutes"] == pytest.approx(24.512413, abs=1e-5)
    # Change one full night to an explicit fixed offset: never pool it into UTC/IANA.
    night = packet["days"][-1]["sources"][0]["sessions"][0]
    for endpoint in ("start", "end"):
        night["metrics"][f"sleep_{endpoint}_at"]["evidence"]["interval_snapshots"][0][
            f"{endpoint}_temporal"].update(source_timezone=None, source_utc_offset_minutes=60)
    assert len(_regularity_view(packet)["sources"][0]["groups"]) == 3
    # Actual DST transition retains one IANA partition even when endpoint offsets differ.
    dst = _regularity_packet(count=1, end=date(2026, 11, 1))
    night = packet["days"][0]["sources"][0]["sessions"][0]
    from copy import deepcopy
    night = deepcopy(night)
    for endpoint, stamp, offset in (("start", "2026-11-01T04:00:00+00:00", -240),
                                    ("end", "2026-11-01T09:00:00+00:00", -300)):
        cell = night["metrics"][f"sleep_{endpoint}_at"]
        cell["value"] = stamp
        snapshot = cell["evidence"]["interval_snapshots"][0]
        snapshot[f"{endpoint}_at_utc"] = stamp
        snapshot[f"{endpoint}_temporal"] = {**snapshot[f"{endpoint}_temporal"],
            "source_timezone": "America/New_York", "source_utc_offset_minutes": offset}
    dst["days"][-1]["sources"] = [{"source": packet["series"][0]["source"], "sessions": [night]}]
    dst["series"] = packet["series"]
    result = _regularity_view(dst, end=date(2026, 11, 1))["sources"][0]
    assert result["eligible_nights"] == 1
    assert result["groups"][0]["partition"]["local_clock_regime"]["zone"] == "America/New_York"


def test_sleep_regularity_keeps_google_selection_source_separation_and_main_role():
    from copy import deepcopy

    from healthcheck.web.sleep_regularity import build_sleep_regularity

    google = _regularity_packet()
    other = deepcopy(google["series"][0])
    other["source"]["source_id"] = "other"
    google["series"].append(other)
    for day in google["days"]:
        group = deepcopy(day["sources"][0])
        group["source"]["source_id"] = "other"
        group["sessions"][0]["record_id"] += "-other"
        day["sources"].append(group)
    garmin = _regularity_packet("garmin")
    timeline = build_sleep_timeline({"garmin": garmin, "google": google}, days=7,
        end_date=date(2026, 10, 8), google_source_id="other")
    rows = timeline["regularity"]["sources"]
    assert [(row["provider"], row["source_id"]) for row in rows] == [
        ("garmin", "sleep"), ("google", "other")]
    assert all(row["eligible_nights"] == 7 for row in rows)
    no_selection = build_sleep_timeline({"google": google}, days=7, end_date=date(2026, 10, 8))
    assert no_selection["regularity"]["sources"] == []
    assert no_selection["regularity"]["state"] == "source_required"
    for day in google["days"]:
        day["sources"][0]["sessions"][0]["role"]["selection"] = "uncertain_session"
    row = _regularity_view(google)["sources"][0]
    assert row["eligible_nights"] == 0 and row["excluded_nights"] == 7
    # No runtime, DB, provider, or export dependency is involved in this adapter call.
    assert build_sleep_regularity({}, [], google_selection={}, days=90,
        end_date=date(2026, 10, 8))["state"] == "unavailable"


def test_sleep_regularity_presentation_rounding_and_undefined_are_not_false_zero():
    from healthcheck.saved_sleep_analysis import circular_local_clock
    from healthcheck.web.sleep_regularity import _clock_view

    assert _clock_view(circular_local_clock([0, 0.1, 0.2]))["text"] == "<1 мин"
    assert _clock_view(circular_local_clock([0, 480, 960]))["text"] == "Нет устойчивого времени"
    assert _clock_view(circular_local_clock([0, 0, 0]))["text"] == "0 мин"


def _seed_regularity_nights(paths):
    """Local synthetic production normalization/persistence, never a provider call."""
    from datetime import datetime

    from healthcheck.garmin.sync import _prepare_normalization_result
    from test_sleep_production_shape import DAY, SOURCE, SURFACE, production_sleep

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            repository = GarminPersistenceRepository(session,
                payload_store=ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts"))
            for index, minutes in enumerate((0, 25, -35, 15, 50, -20, 5, 40, -10, 10)):
                day = END - timedelta(days=9 - index)
                shift = timedelta(days=(day - DAY).days, minutes=minutes)
                payload = production_sleep()
                daily = payload["dailySleepDTO"]
                daily["calendarDate"] = day.isoformat()
                for key in ("sleepStartTimestampGMT", "sleepEndTimestampGMT",
                            "sleepStartTimestampLocal", "sleepEndTimestampLocal"):
                    daily[key] += int(shift.total_seconds() * 1000)
                for stage in payload["sleepLevels"]:
                    for key in ("startGMT", "endGMT"):
                        stage[key] = (datetime.fromisoformat(stage[key]) + shift).isoformat()
                normalized = normalize_garmin_payload(
                    payload, stream="sleep", source_identity=SOURCE)
                repository.persist_result(_prepare_normalization_result(
                    SURFACE, payload, normalized, day=day), payload=payload)
                google = _google_sleep_payload(name=f"regularity-synthetic-{index}")
                component = google["dataPoints"][0]["sleep"]
                interval = component["interval"]
                for endpoint in ("start", "end"):
                    instant = datetime.fromisoformat(interval[f"{endpoint}Time"]) + shift
                    interval[f"{endpoint}Time"] = instant.isoformat()
                    local = instant + timedelta(hours=3)
                    interval[f"civil{endpoint.title()}Time"].update(
                        date=local.date().isoformat(),
                        time=local.time().replace(tzinfo=None).isoformat())
                _persist_google(session, paths, payload=google)
    finally:
        engine.dispose()


@pytest.mark.parametrize("days,expected_nights", [(7, 7), (30, 10)])
def test_sleep_regularity_production_http_packet_and_period_switch(tmp_path, days, expected_nights):
    app, _, paths = _ui(tmp_path)
    _seed_regularity_nights(paths)
    with client_for(app) as client:
        response = client.get(f"/sleep?days={days}&wake_date={END}")
    assert response.status_code == 200
    packet = _timeline_json(response.text)
    rows = packet["regularity"]["sources"]
    assert [row["provider"] for row in rows] == ["garmin", "google"]
    assert all(row["eligible_nights"] == expected_nights for row in rows)
    assert all(len(row["groups"]) == 1 for row in rows)
    assert all(row["groups"][0]["start"]["state"] == "sufficient" for row in rows)
    assert 'data-sleep-regularity' in response.text
    primary = response.text.split('data-sleep-regularity>', 1)[1].split('<details', 1)[0]
    assert 'Засыпание' in primary and 'Подъём' in primary
    assert 'circular_sd' not in primary and 'complete_stage_boundary' not in primary
    assert 'social_jetlag' not in json.dumps(packet["regularity"])
    assert packet["start_date"] == (END - timedelta(days=days - 1)).isoformat()
