"""Owner /sleep presentation regressions for the #297 Google daily-vitals block."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import event

from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.google.contracts import GoogleQueryMode
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from test_garmin_query_dashboard import _ui
from test_google_daily_vitals import (
    HRV,
    RHR,
    _daily_record,
    _fitbit_identity,
    _persist,
    _query,
    seed_google_daily_vitals,
)


def client_for(app):
    return TestClient(app, base_url="http://127.0.0.1:8120")


def _split(page_text: str) -> tuple[str, str]:
    return page_text.split('<details class="card owner-details', 1)


def test_sleep_google_vitals_block_is_source_explicit_and_unpaired(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    seed_google_daily_vitals(paths)
    app.state.engine = create_sqlite_engine(paths)
    with client_for(app) as client:
        page = client.get("/sleep?wake_date=2099-01-02")
    assert page.status_code == 200
    primary, technical = _split(page.text)
    assert "Google дневные показатели" in primary
    assert primary.count('data-google-source="') == 2
    assert "Google · Fitbit Air" in primary
    assert "Google · семейство устройств (google-wearables)" in primary
    assert "42.5 мс" in primary
    assert "55 уд/мин" in primary
    assert "97 %" in primary and "96 %" in primary
    assert "13.5 вдохов/мин" in primary
    assert "0 вдохов/мин" in primary
    assert "явный ноль" in primary
    assert "Источник передал пустое значение за эту дату." in primary
    assert "Нет текущих записей в окне" in primary
    # Google values render even without any Garmin source/pairing.
    assert "Нет доступного источника Garmin" in primary
    # Primary Owner UI never exposes raw metric codes, contract versions or ids.
    assert "daily_hrv_average_ms" not in primary
    assert "r297-google-daily-vitals-read-v1" not in primary
    assert "google-record-" not in primary
    assert "candidates" not in primary
    assert "r297-google-daily-vitals-read-v1" in technical
    assert "candidates" in technical


def test_sleep_google_vitals_windows_are_bounded_and_defaulted(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    seed_google_daily_vitals(paths)
    with client_for(app) as client:
        week = client.get("/sleep?wake_date=2099-01-02&vitals_window=7")
        assert week.status_code == 200
        primary, _technical = _split(week.text)
        assert "2098-12-27 → 2099-01-02" in primary
        assert 'value="7" selected' in primary

        quarter = client.get("/sleep?wake_date=2099-01-02&vitals_window=90")
        primary, _technical = _split(quarter.text)
        assert "2098-10-05 → 2099-01-02" in primary
        assert 'value="90" selected' in primary

        out_of_set = client.get("/sleep?wake_date=2099-01-02&vitals_window=365")
        primary, _technical = _split(out_of_set.text)
        assert "2098-12-04 → 2099-01-02" in primary
        assert 'value="30" selected' in primary

        invalid = client.get("/sleep?wake_date=2099-01-02&vitals_window=nope")
        assert invalid.status_code == 200
        primary, _technical = _split(invalid.text)
        assert "2098-12-04 → 2099-01-02" in primary


def test_sleep_google_vitals_ambiguous_and_unit_mismatch_are_honest(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGooglePayloadStore(paths.root / "artifacts")
            identity = _fitbit_identity()
            for mode in (GoogleQueryMode.LIST, GoogleQueryMode.RECONCILE):
                _persist(
                    session,
                    store,
                    _daily_record(metric_code=HRV, local_date=date(2099, 1, 2), value=40),
                    identity=identity,
                    query=_query(mode),
                )
            _persist(
                session,
                store,
                _daily_record(
                    metric_code=RHR, local_date=date(2099, 1, 2), value=55, unit="seconds"
                ),
                identity=identity,
            )
    finally:
        engine.dispose()
    with client_for(app) as client:
        page = client.get("/sleep?wake_date=2099-01-02")
    assert page.status_code == 200
    primary, _technical = _split(page.text)
    assert "несколько текущих записей" in primary
    assert "Единица измерения записи не совпадает с ожидаемой." in primary
    assert "40 мс" not in primary


def test_sleep_google_vitals_empty_window_is_window_scoped(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with client_for(app) as client:
        page = client.get("/sleep?wake_date=2099-01-02")
    assert page.status_code == 200
    primary, _technical = _split(page.text)
    assert "Нет текущих записей Google в выбранном окне" in primary
    assert "не доказывает отсутствие данных за пределами окна" in primary


def test_sleep_google_vitals_page_reads_without_writes(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    seed_google_daily_vitals(paths)
    app.state.engine = create_sqlite_engine(paths)
    statements: list[str] = []
    with client_for(app) as client:
        event.listen(
            app.state.engine,
            "before_cursor_execute",
            lambda _c, _cur, sql, *_a: statements.append(sql),
        )
        page = client.get("/sleep?wake_date=2099-01-02")
        assert page.status_code == 200
    assert "BEGIN" in statements
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )


def test_sleep_google_vitals_database_unavailable_stays_honest(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    with client_for(app) as client:
        assert client.get("/sleep").status_code == 200
    app.state.engine.dispose()
    paths.database.unlink()
    with client_for(app) as client:
        page = client.get("/sleep")
        assert page.status_code == 200
        assert page.text.count("Локальное хранилище данных не готово") >= 2
        assert "data-google-vitals" in page.text


def test_sleep_google_vitals_window_ends_at_selected_date(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    seed_google_daily_vitals(paths)
    with client_for(app) as client:
        page = client.get("/sleep?wake_date=2099-01-01")
    assert page.status_code == 200
    primary, _technical = _split(page.text)
    assert "57 уд/мин" in primary
    assert "2099-01-01" in primary
    assert "42.5" not in primary
    assert primary.count('data-google-source="') == 1
