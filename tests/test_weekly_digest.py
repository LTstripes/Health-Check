"""Synthetic saved-store and HTTP entry points for the Sunday preview."""

import hashlib
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from healthcheck import combined_evidence, combined_movement
from healthcheck import weekly_digest as weekly
from healthcheck.chat_evidence import EvidenceError, _json
from healthcheck.chat_evidence_mcp import MCPConfig, create_app
from healthcheck.config import Settings
from healthcheck.db.engine import session_scope
from healthcheck.db.models import GarminRecordMetric, GoogleRecordMetric
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.web.ui_app import create_ui_app
from test_chat_evidence_mcp import HEADERS, rpc
from test_combined_evidence import (
    _seed_completed_steps,
    _seed_movement,
)
from test_combined_evidence import profile as _combined_profile
from test_google_steps_countsum import payload, persist
from test_period_summary import _activity
from test_sleep_evidence import profile as _sleep_profile

sleep_profile = _sleep_profile
profile = _combined_profile
END = date(2099, 1, 4)
CLOCK = datetime(2099, 1, 4, 17, tzinfo=UTC)


def config(profile, **changes):
    request = profile[2]
    return replace(weekly.WeeklyDigestConfig(
        request.activity_garmin_source_id, request.sleep_garmin_source_id,
        request.sleep_google_source_id), **changes)


def read(profile, **kwargs):
    return weekly.get_weekly_digest_evidence(
        profile=profile[0].root, profile_kind="synthetic",
        config=kwargs.pop("config", config(profile)),
        week_end=kwargs.pop("week_end", END),
        evaluated_at_utc=kwargs.pop("clock", CLOCK), **kwargs)


def seed_google(profile, value="0"):
    with session_scope(profile[1]) as session:
        _, saved = persist((profile[0], session, ContentAddressedGooglePayloadStore(
            profile[0].root / "artifacts")), payload(value))
        return saved.source.id


def test_one_snapshot_exact_sources_frozen_renderer_hash_readonly(profile, monkeypatch):
    steps = _seed_movement(profile)
    google_steps = seed_google(profile, "123")
    cfg = config(profile, steps_garmin_source_id=steps, steps_google_source_id=google_steps)
    original = combined_evidence._read_session
    sessions = []
    @contextmanager
    def inspected(root):
        with original(root) as session:
            sessions.append(session)
            yield session
    monkeypatch.setattr(combined_evidence, "_read_session", inspected)
    def fingerprint():
        # SQLite's read coordination may update -shm; no application write.
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in profile[0].root.rglob("*")
                if p.is_file() and not p.name.endswith("-shm")}
    before = fingerprint()
    packet = read(profile, config=cfg)
    assert len(sessions) == 1
    assert fingerprint() == before
    assert packet["evidence"]["request"]["days"] == 7
    assert packet["evidence"]["snapshot"] == "one_sqlite_read_transaction"
    assert packet["evidence"]["sections"]["google_steps"]["source_id"] == google_steps
    assert "source_choices" not in weekly.encode_weekly_digest(packet)
    assert packet["text"] == weekly.render_weekly_digest(packet)
    assert len(sessions) == 1  # frozen renderer never reads
    body = dict(packet)
    digest = body.pop("digest_hash")
    assert hashlib.sha256(_json(body).encode()).hexdigest() == digest
    assert packet["delivery"]["schedule_enabled"] is False
    assert packet["collection_freshness"]["state"] == "unknown"
    assert packet["period"]["as_of"] == "2099-01-04T20:00:00+03:00"
    assert packet["period"]["sunday_incomplete"] is True
    assert "итог предварительный" in packet["text"]
    assert "1 из 7 дат" in packet["text"]
    assert "0 шагов" in packet["text"] and "123 шагов" in packet["text"]


def test_reuses_activity_reducers_invalid_field_does_not_remove_session(profile):
    with session_scope(profile[1]) as session:
        metric = session.scalar(select(GarminRecordMetric).where(
            GarminRecordMetric.metric_code == "distance_meters"))
        metric.state, metric.value_number = "invalid", None
        _activity(session, profile[0], day=date(2099, 1, 3), kind="soccer")
    packet = read(profile)
    cell = packet["evidence"]["sections"]["activity"]["providers"]["garmin"]["metrics"]
    assert cell["activity_session_count"]["aggregation"]["value"] == 3
    assert "3 тренировки" in packet["text"] and "футбол" in packet["text"]
    assert "Велосипед:" not in packet["text"]
    assert "Теннис:" in packet["text"]


def test_empty_week_is_unknown_not_no_activity_or_zero_steps(profile):
    packet = read(profile, week_end=END + timedelta(days=7),
                  clock=CLOCK + timedelta(days=7))
    assert "0 тренировок" not in packet["text"]
    assert "0 шагов" not in packet["text"]
    assert "нет" in packet["text"]
    assert "пригодной длительности" in packet["text"]
    assert packet["comparison"]["state"] == "not_performed"


def test_completed_steps_excludes_unfinished_sunday(profile):
    identity = _seed_completed_steps(profile)
    _seed_completed_steps(profile, day=END, at=CLOCK)
    packet = read(profile, config=config(
        profile, steps_garmin_source_id=identity, steps_view="completed"))
    steps = packet["evidence"]["sections"]["steps"]
    assert steps["completed_day_count"] == 6
    assert steps["excluded_uncompleted_day_count"] == 1
    assert all(str(cell["calendar_date"]) != str(END) for cell in steps["cells"])
    assert "1 из 6 дат" in packet["text"]


@pytest.mark.parametrize("offset", [timedelta(minutes=1), timedelta(days=2)])
def test_late_read_uses_actual_clock_never_sunday_time_travel(profile, offset):
    packet = read(profile, clock=CLOCK + offset)
    assert packet["period"]["late_read"] is True
    assert packet["period"]["as_of"] == (CLOCK + offset).astimezone(weekly.MOSCOW).isoformat()
    assert "не восстановление на 20:00" in packet["text"]
    assert packet["period"]["sunday_incomplete"] == (offset < timedelta(days=1))


@pytest.mark.parametrize("end,clock,reason", [
    (date(2099, 1, 2), CLOCK, "weekly_end_must_be_sunday"),
    (True, CLOCK, "weekly_end_must_be_sunday"),
    (END + timedelta(days=7), CLOCK, "future_week_not_available"),
    (END, datetime(2099, 1, 4), "aware_evaluation_clock_required"),
])
def test_window_arguments_rejected_before_read(profile, monkeypatch, end, clock, reason):
    def forbidden(**kwargs):
        pytest.fail("invalid window must not read")
    monkeypatch.setattr(weekly, "read_combined_evidence", forbidden)
    with pytest.raises(EvidenceError, match=reason):
        read(profile, week_end=end, clock=clock)


@pytest.mark.parametrize("field", ["activity_garmin_source_id", "sleep_google_source_id",
                                   "steps_garmin_source_id", "steps_google_source_id"])
def test_invalid_explicit_source_fails_no_fallback(profile, field):
    with pytest.raises(EvidenceError, match="selected_source_unavailable"):
        read(profile, config=config(profile, **{field: "nonexistent"}))


def test_google_closed_projection_caps_and_output_budget(profile, monkeypatch):
    from healthcheck.google import steps_read
    identity = seed_google(profile)
    cfg = config(profile, steps_google_source_id=identity)
    original = steps_read.read_saved_steps_window
    def injected(*args, **kwargs):
        result = original(*args, **kwargs)
        result["raw_body"] = "POISON_PRIVATE"
        result["source_choices"] = [{"source_id": "POISON_UNRELATED"}]
        if result["cells"]:
            result["cells"][0]["gps"] = "POISON_ROUTE"
        return result
    monkeypatch.setattr(steps_read, "read_saved_steps_window", injected)
    assert "POISON" not in weekly.encode_weekly_digest(read(profile, config=cfg))
    monkeypatch.setattr(steps_read, "MAX_RECORDS", 0)
    with pytest.raises(EvidenceError, match="google_steps_search_incomplete"):
        read(profile, config=cfg)
    monkeypatch.setattr(steps_read, "MAX_RECORDS", 4096)
    monkeypatch.setattr(weekly, "MAX_OUTPUT_BYTES", 1)
    with pytest.raises(EvidenceError, match="output_exceeds_byte_limit"):
        read(profile)


def test_google_nested_non_scalar_rejected(profile, monkeypatch):
    original = combined_movement.read_google_steps
    # Public projection rejects future nested scalar fields before weekly rendering.
    from healthcheck.google import steps_read
    saved = steps_read.read_saved_steps_window
    def injected(*args, **kwargs):
        result = saved(*args, **kwargs)
        result["cells"][0]["value"] = {"secret": "POISON"}
        return result
    identity = seed_google(profile)
    monkeypatch.setattr(steps_read, "read_saved_steps_window", injected)
    with pytest.raises(EvidenceError, match="unsupported_evidence_value"):
        read(profile, config=config(profile, steps_google_source_id=identity))
    assert original is combined_movement.read_google_steps


def test_frozen_retry_offline_failure_does_not_fabricate_digest(profile, monkeypatch):
    packet = read(profile)
    encoded = weekly.encode_weekly_digest(packet)
    def offline(**kwargs):
        raise EvidenceError("evidence_read_failed")
    monkeypatch.setattr(weekly, "read_combined_evidence", offline)
    assert weekly.encode_weekly_digest(packet) == encoded
    assert weekly.render_weekly_digest(packet) == packet["text"]
    with pytest.raises(EvidenceError, match="evidence_read_failed"):
        read(profile)


def test_mcp_opt_in_exact_arguments_and_errors(profile, monkeypatch):
    from healthcheck import chat_evidence_mcp as mcp
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return CLOCK.astimezone(tz)
    monkeypatch.setattr(mcp, "datetime", Clock)
    cfg = MCPConfig(profile[0].root, "synthetic", ZoneInfo("Europe/Moscow"))
    with TestClient(create_app(cfg), base_url="http://127.0.0.1", headers=HEADERS) as http:
        assert len(rpc(http, "tools/list").json()["result"]["tools"]) == 1
        assert "error" in rpc(http, "tools/call", {
            "name": "get_weekly_digest_evidence", "arguments": {"week_end": str(END)}}).json()
    with TestClient(create_app(replace(cfg, weekly_digest=config(profile))),
                    base_url="http://127.0.0.1", headers=HEADERS) as http:
        tools = rpc(http, "tools/list").json()["result"]["tools"]
        assert len(tools) == 2
        assert set(tools[1]["inputSchema"]["properties"]) == {"week_end"}
        def call(args):
            return rpc(http, "tools/call", {
                "name": "get_weekly_digest_evidence", "arguments": args}).json()
        result = call({"week_end": str(END)})["result"]
        assert not result["isError"] and result["structuredContent"]["version"] == weekly.VERSION
        assert result["content"][0]["text"] == result["structuredContent"]["text"]
        for extra in ("profile", "sources", "days", "sql", "domains"):
            assert "error" in call({"week_end": str(END), extra: "invalid"})
        assert call({"week_end": "2099-02-31"})["result"]["isError"]
        assert call({"week_end": "2099-01-02"})["result"]["isError"]


def test_overview_opt_in_card_and_no_new_route(profile, monkeypatch):
    from healthcheck.web import pages
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return CLOCK.astimezone(tz)
    monkeypatch.setattr(pages, "datetime", Clock)
    settings = Settings(data_dir=profile[0].root)
    app, _ = create_ui_app(settings)
    url = "/brief?start_date=2098-12-29&end_date=2099-01-04&weekly_end=2099-01-04"
    with TestClient(app, base_url="http://127.0.0.1:8120") as http:
        assert 'data-weekly-preview' not in http.get(url).text
    app, _ = create_ui_app(settings, weekly_digest=config(profile), profile_kind="synthetic")
    with TestClient(app, base_url="http://127.0.0.1:8120") as http:
        response = http.get(url)
        assert response.status_code == 200
        assert 'data-weekly-preview' in response.text
        assert "Итог недели · preview" in response.text
        assert "Подробности и основания" in response.text
        assert "автоматическая отправка не включена" in response.text
        assert "итог предварительный" in response.text
        assert "Не удалось прочитать недельный итог" in http.get(url.replace(
            "weekly_end=2099-01-04", "weekly_end=2099-01-02")).text
        # Optional local visual evidence, never a runtime launch or real profile.
        if target := os.environ.get("HEALTHCHECK_WEEKLY_PREVIEW_DIR"):
            output = Path(target)
            output.mkdir(parents=True, exist_ok=True)
            (output / "overview.html").write_text(response.text, encoding="utf-8")


def test_optional_ui_requires_explicit_profile_assertion(profile):
    with pytest.raises(ValueError, match="explicit_profile_classification_required"):
        create_ui_app(Settings(data_dir=profile[0].root), weekly_digest=config(profile))


@pytest.mark.parametrize("role", ["nap", "unknown", "collision", "invalid_duration"])
def test_sleep_accepted_roles_and_duration_gates(profile, role):
    from test_sleep_metrics import _google_sleep_payload, _persist_google
    with session_scope(profile[1]) as session:
        if role == "collision":
            _persist_google(session, profile[0], payload=_google_sleep_payload(name="second-main"))
        elif role == "invalid_duration":
            metric = session.scalar(select(GoogleRecordMetric).where(
                GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"))
            metric.state, metric.value_number, metric.value_text = "invalid", None, None
        else:
            for metric in session.scalars(select(GoogleRecordMetric).where(
                GoogleRecordMetric.metric_code.in_(("sleep_metadata_main", "sleep_metadata_nap"))
            )):
                if role == "nap":
                    metric.value_text = "true" if metric.metric_code.endswith("nap") else "false"
                else:
                    metric.state, metric.value_text = "missing", None
    packet = read(profile)
    assert "Сон Google: пригодной длительности основного сна нет" in packet["text"]
    assert packet["evidence"]["sections"]["sleep"]["providers"]["google"]["source_range"]


def test_full_activity_and_google_steps_seven_dates_no_cross_source_sum(profile):
    from test_google_steps_countsum import civil
    with session_scope(profile[1]) as session:
        for day in range(7):
            current = END - timedelta(days=6 - day)
            _activity(session, profile[0], day=current, kind="walking", suffix=str(day))
        # Seven Google civil dates, exact family, each observed rather than finalized.
        store = ContentAddressedGooglePayloadStore(profile[0].root / "artifacts")
        from healthcheck.google.persistence import GooglePersistenceRepository
        from test_google_steps_countsum import normalize
        for day in range(5, 12):
            raw = payload(str(day), start=civil(day), end=civil(day + 1))
            saved = GooglePersistenceRepository(session, payload_store=store).persist_result(
                normalize(raw), payload=raw, received_at=CLOCK)
        identity = saved.source.id
    packet = read(profile, week_end=date(2099, 1, 11), clock=CLOCK + timedelta(days=7),
                  config=config(profile, steps_google_source_id=identity))
    # Seven observed days still do not prove provider coverage/finality.
    assert "7 из 7 дат" in packet["text"]
    assert "Недельные сумма и среднее не рассчитаны" in packet["text"]
    assert "11 шагов" in packet["text"]
    full = read(profile)
    assert "Даты с записями: 7 из 7" in full["text"]
    assert "Это не подтверждает полноту реальной активности" in full["text"]
