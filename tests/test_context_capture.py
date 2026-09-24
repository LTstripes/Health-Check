"""Synthetic contract regressions for issue #177 Context Capture v0."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DatabaseError

from healthcheck.cli import main
from healthcheck.config import Settings
from healthcheck.context import (
    ContextConflictError,
    ContextService,
    ContextValidationError,
    parse_date_only,
    parse_interval,
    parse_timestamp,
)
from healthcheck.context.service import MAX_LIST_RESULTS, MAX_TEXT_LENGTH, TemporalValue
from healthcheck.db.engine import (
    _alembic_config,
    create_sqlite_engine,
    database_readiness,
    migrate_database,
    session_scope,
)
from healthcheck.db.models import (
    ContextEventHead,
    ContextEventRevision,
    ContextRevisionTag,
    ContextTag,
)
from healthcheck.runtime import prepare_runtime


def _runtime(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    return settings, paths, create_sqlite_engine(paths)


def test_date_only_add_preserves_original_text_without_inventing_utc(tmp_path: Path) -> None:
    _settings, _paths, engine = _runtime(tmp_path)
    original = "  Теннис вечером; устал сильнее обычного.  "
    try:
        with session_scope(engine) as session:
            view = ContextService(session).add(
                text=original,
                temporal=parse_date_only("2026-09-22"),
                capture_source="cli",
                tags=(" Tennis ", "FATIGUE", "tennis"),
                operation_id="add-date-1",
            )
            assert view.original_text == original
            assert view.temporal.kind == "date"
            assert view.temporal.start_precision == "date"
            assert view.temporal.start_at_utc is None
            assert view.temporal.start_utc_offset_minutes is None
            assert [(tag.name, tag.status, tag.provenance_source) for tag in view.tags] == [
                ("fatigue", "confirmed", "cli"),
                ("tennis", "confirmed", "cli"),
            ]
    finally:
        engine.dispose()


def test_explicit_timestamp_and_interval_preserve_offset_and_validate_zone() -> None:
    instant = parse_timestamp("2026-09-22T19:30+03:00", timezone_name="Europe/Moscow")
    assert instant.start_precision == "minute"
    assert instant.start_utc_offset_minutes == 180
    assert instant.start_source_timestamp == "2026-09-22T19:30+03:00"
    assert instant.start_at_utc is not None
    assert instant.start_at_utc.isoformat() == "2026-09-22T16:30:00+00:00"

    interval = parse_interval(
        "2026-09-22T19:30:00+03:00",
        "2026-09-22T21:00:00+03:00",
        timezone_name="Europe/Moscow",
    )
    assert interval.kind == "interval"
    assert interval.start_precision == "second"
    assert interval.end_utc_offset_minutes == 180

    date_interval = parse_interval("2026-09-20", "2026-09-22")
    assert date_interval.start_precision == "date"
    assert date_interval.end_precision == "date"
    assert date_interval.start_at_utc is None
    assert date_interval.end_at_utc is None

    with pytest.raises(ContextValidationError, match="explicit"):
        parse_timestamp("2026-09-22T19:30")
    with pytest.raises(ContextValidationError, match="offset is unknown"):
        parse_timestamp("2026-09-22T19:30-00:00")
    with pytest.raises(ContextValidationError, match="offset is unknown"):
        parse_interval("2026-09-22T19:30-00:00", "2026-09-22T20:30+00:00")
    with pytest.raises(ContextValidationError, match="offset is unknown"):
        parse_interval("2026-09-22T19:30+00:00", "2026-09-22T20:30-00:00")
    with pytest.raises(ContextValidationError, match="does not match"):
        parse_timestamp("2026-09-22T19:30+02:00", timezone_name="Europe/Moscow")
    with pytest.raises(ContextValidationError, match="later"):
        parse_interval("2026-09-22T21:00+03:00", "2026-09-22T19:30+03:00")
    with pytest.raises(ContextValidationError, match="earlier"):
        parse_interval("2026-09-23", "2026-09-22")
    with pytest.raises(ContextValidationError, match="same temporal precision"):
        parse_interval("2026-09-22", "2026-09-23T12:00+03:00")
    with pytest.raises(ContextValidationError, match="same temporal precision"):
        parse_interval("2026-09-22T19:30+03:00", "2026-09-22T20:30:00+03:00")
    with pytest.raises(ContextValidationError, match="same temporal precision"):
        parse_interval(
            "2026-09-22T19:30:00+03:00",
            "2026-09-22T20:30:00.123456+03:00",
        )


def test_revise_is_append_only_advances_head_and_retries_idempotently(tmp_path: Path) -> None:
    _settings, _paths, engine = _runtime(tmp_path)
    try:
        with session_scope(engine) as session:
            service = ContextService(session)
            first = service.add(
                text="Synthetic initial note",
                temporal=parse_date_only("2026-09-20"),
                capture_source="manual",
                tags=("stress",),
                operation_id="add-idempotent-1",
            )
            replay = service.add(
                text="Synthetic initial note",
                temporal=parse_date_only("2026-09-20"),
                capture_source="manual",
                tags=("stress",),
                operation_id="add-idempotent-1",
            )
            assert replay.revision_id == first.revision_id

            second = service.revise(
                first.event_id,
                text="Synthetic corrected note",
                tags=("unusual stress", "travel"),
                capture_source="manual",
                operation_id="revise-idempotent-1",
            )
            replay_second = service.revise(
                first.event_id,
                text="Synthetic corrected note",
                tags=("travel", "unusual_stress"),
                capture_source="manual",
                operation_id="revise-idempotent-1",
            )
            assert replay_second.revision_id == second.revision_id
            assert second.revision_number == 2
            third = service.revise(
                first.event_id,
                tags=("later tag",),
                capture_source="manual",
                operation_id="revise-later-1",
            )
            replay_after_head_advanced = service.revise(
                first.event_id,
                text="Synthetic corrected note",
                tags=("travel", "unusual_stress"),
                capture_source="manual",
                operation_id="revise-idempotent-1",
            )
            assert replay_after_head_advanced.revision_id == second.revision_id
            assert third.revision_number == 3
            current = service.list()
            history = service.list(history=True)
            assert [row.revision_id for row in current] == [third.revision_id]
            assert {row.revision_number: row.is_current for row in history} == {
                1: False,
                2: False,
                3: True,
            }
            head = session.get(ContextEventHead, first.event_id)
            assert head is not None and head.revision_id == third.revision_id

            with pytest.raises(ContextConflictError, match="different context input"):
                service.add(
                    text="Different input",
                    temporal=parse_date_only("2026-09-20"),
                    operation_id="add-idempotent-1",
                )
            with pytest.raises(ContextConflictError, match="different context input"):
                service.revise(
                    first.event_id,
                    operation_id="add-idempotent-1",
                )

        with engine.begin() as connection:
            with pytest.raises(DatabaseError, match="append-only"):
                connection.execute(
                    text(
                        "UPDATE context_event_revisions SET original_text = 'mutated' "
                        "WHERE id = :revision_id"
                    ),
                    {"revision_id": first.revision_id},
                )
    finally:
        engine.dispose()


def test_text_only_cross_source_revise_preserves_inherited_tag_provenance(tmp_path: Path) -> None:
    _settings, _paths, engine = _runtime(tmp_path)
    try:
        with session_scope(engine) as session:
            service = ContextService(session)
            original = service.add(
                text="Synthetic manual context",
                temporal=parse_date_only("2026-09-22"),
                capture_source="manual",
                tags=(" Travel ",),
                operation_id="provenance-add",
            )
            future_tag = ContextTag(normalized_name="future-suggestion")
            session.add(future_tag)
            session.flush()
            session.add(
                ContextRevisionTag(
                    revision_id=original.revision_id,
                    tag_id=future_tag.id,
                    status="suggested",
                    provenance_source="ai",
                )
            )
            session.flush()
            text_only = service.revise(
                original.event_id,
                text="Synthetic corrected context",
                capture_source="cli",
                operation_id="provenance-text-only",
            )
            assert text_only.capture_source == "cli"
            assert [(tag.name, tag.status, tag.provenance_source) for tag in text_only.tags] == [
                ("future-suggestion", "suggested", "ai"),
                ("travel", "confirmed", "manual")
            ]
            retagged = service.revise(
                original.event_id,
                tags=("Late Sleep",),
                capture_source="cli",
                operation_id="provenance-retag",
            )
            assert [(tag.name, tag.status, tag.provenance_source) for tag in retagged.tags] == [
                ("late-sleep", "confirmed", "cli")
            ]
            assert service.list(history=True)[-1].tags == text_only.tags
    finally:
        engine.dispose()


def test_bounded_list_is_deterministic_and_filters_interval_overlap(tmp_path: Path) -> None:
    _settings, _paths, engine = _runtime(tmp_path)
    try:
        with session_scope(engine) as session:
            service = ContextService(session)
            older = service.add(
                text="Synthetic travel interval",
                temporal=parse_interval(
                    "2026-09-01T22:00+03:00", "2026-09-03T08:00+03:00"
                ),
                operation_id="list-interval",
            )
            newer = service.add(
                text="Synthetic later event",
                temporal=parse_date_only("2026-09-10"),
                operation_id="list-date",
            )
            filtered = service.list(
                from_date=date(2026, 9, 3), to_date=date(2026, 9, 9), limit=10
            )
            assert [row.event_id for row in filtered] == [older.event_id]
            assert [row.event_id for row in service.list(limit=2)] == [
                newer.event_id,
                older.event_id,
            ]
            with pytest.raises(ContextValidationError, match="between"):
                service.list(limit=MAX_LIST_RESULTS + 1)
            with pytest.raises(ContextValidationError, match="must not be later"):
                service.list(from_date=date(2026, 9, 2), to_date=date(2026, 9, 1))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "text_value,tags,error",
    [
        ("   ", (), "whitespace"),
        ("x" * (MAX_TEXT_LENGTH + 1), (), "exceeds"),
        ("synthetic", ("bad/tag",), "punctuation"),
        ("synthetic", ("_" * 4,), "letter or digit"),
    ],
)
def test_malformed_and_oversize_input_fails_closed(
    tmp_path: Path,
    text_value: str,
    tags: tuple[str, ...],
    error: str,
) -> None:
    _settings, _paths, engine = _runtime(tmp_path)
    try:
        with session_scope(engine) as session:
            with pytest.raises(ContextValidationError, match=error):
                ContextService(session).add(
                    text=text_value,
                    temporal=parse_date_only("2026-09-22"),
                    tags=tags,
                )
    finally:
        engine.dispose()


def test_typed_service_rejects_internally_inconsistent_temporal_value(tmp_path: Path) -> None:
    _settings, _paths, engine = _runtime(tmp_path)
    try:
        with session_scope(engine) as session:
            with pytest.raises(ContextValidationError, match="internally inconsistent"):
                ContextService(session).add(
                    text="Synthetic inconsistent timestamp",
                    temporal=TemporalValue(
                        kind="instant",
                        start_precision="minute",
                        start_local_date=date(2026, 9, 22),
                        start_source_timestamp="2026-09-22T19:30+03:00",
                        start_utc_offset_minutes=0,
                    ),
                )
    finally:
        engine.dispose()


def test_schema_rejects_mixed_timestamp_interval_precision(tmp_path: Path) -> None:
    _settings, _paths, engine = _runtime(tmp_path)
    try:
        with session_scope(engine) as session:
            event = ContextService(session).add(
                text="Synthetic schema-constraint anchor",
                temporal=parse_date_only("2026-09-22"),
                operation_id="mixed-precision-anchor",
            )

        with engine.begin() as connection:
            with pytest.raises(DatabaseError, match="temporal_shape_valid"):
                connection.execute(
                    text(
                        "INSERT INTO context_event_revisions ("
                        "id, event_id, revision_number, operation_id, operation_kind, "
                        "request_fingerprint, original_text, capture_source, temporal_kind, "
                        "start_precision, end_precision, start_local_date, end_local_date, "
                        "start_at_utc, end_at_utc, start_source_timestamp, "
                        "end_source_timestamp, start_utc_offset_minutes, "
                        "end_utc_offset_minutes"
                        ") VALUES ("
                        "'mixed-precision-revision', :event_id, 2, 'mixed-precision-op', "
                        "'revise', :fingerprint, 'Synthetic mixed precision', 'manual', "
                        "'interval', 'minute', 'second', '2026-09-22', '2026-09-22', "
                        "'2026-09-22 16:30:00', '2026-09-22 17:30:00', "
                        "'2026-09-22T19:30+03:00', '2026-09-22T20:30:00+03:00', 180, 180)"
                    ),
                    {"event_id": event.event_id, "fingerprint": "0" * 64},
                )
    finally:
        engine.dispose()


def test_populated_0012_database_upgrades_additively_and_preserves_unrelated_data(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "populated-runtime")
    paths = prepare_runtime(settings)
    command.upgrade(_alembic_config(paths), "0012_r05_agreement_successor_publication")
    engine = create_sqlite_engine(paths)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO providers (id, code, display_name, provider_kind) "
                    "VALUES ('synthetic-provider-177', 'synthetic-177', "
                    "'Synthetic Provider', 'test')"
                )
            )
            before = connection.execute(
                text("SELECT id, code, display_name, provider_kind FROM providers")
            ).all()
        command.upgrade(_alembic_config(paths), "0013_context_capture_v0")
        with engine.connect() as connection:
            after = connection.execute(
                text("SELECT id, code, display_name, provider_kind FROM providers")
            ).all()
            tables = set(inspect(connection).get_table_names())
            assert after == before
            assert {
                "context_events",
                "context_event_revisions",
                "context_event_heads",
                "context_tags",
                "context_revision_tags",
            } <= tables
        assert database_readiness(paths)["migration_revision"] == "0013_context_capture_v0"
    finally:
        engine.dispose()


def test_cli_add_list_revise_is_typed_and_privacy_safe(tmp_path: Path, capsys) -> None:
    settings, paths, engine = _runtime(tmp_path)
    engine.dispose()
    data_dir = str(settings.data_dir)
    note = "Синтетическая заметка о позднем сне"
    assert main(
        [
            "context-add",
            "--data-dir",
            data_dir,
            "--date",
            "2026-09-22",
            "--text",
            note,
            "--tag",
            "Late Sleep",
            "--operation-id",
            "cli-add-177",
        ]
    ) == 0
    add_output = json.loads(capsys.readouterr().out)
    assert "text" not in add_output
    assert add_output["tags"][0]["status"] == "confirmed"

    assert main(
        [
            "context-list",
            "--data-dir",
            data_dir,
            "--from",
            "2026-09-01",
            "--to",
            "2026-09-30",
        ]
    ) == 0
    list_output = json.loads(capsys.readouterr().out)
    assert list_output["events"][0]["text"] == note

    assert main(
        [
            "context-revise",
            "--data-dir",
            data_dir,
            "--event-id",
            add_output["event_id"],
            "--text",
            "Синтетическая исправленная заметка",
            "--clear-tags",
            "--operation-id",
            "cli-revise-177",
        ]
    ) == 0
    revise_output = json.loads(capsys.readouterr().out)
    assert revise_output["revision_number"] == 2
    assert revise_output["tags"] == []
    assert "text" not in revise_output

    assert main(
        [
            "context-revise",
            "--data-dir",
            data_dir,
            "--event-id",
            add_output["event_id"],
            "--text",
            "Synthetic orphan-zone correction",
            "--timezone",
            "Europe/Moscow",
        ]
    ) == 2
    assert "--timezone requires" in capsys.readouterr().err
    assert main(["context-list", "--data-dir", data_dir]) == 0
    assert json.loads(capsys.readouterr().out)["events"][0]["revision_number"] == 2

    secret_prefix = "PRIVATE-NOTE-MUST-NOT-ECHO"
    assert main(
        [
            "context-add",
            "--data-dir",
            str(paths.root),
            "--date",
            "2026-09-22",
            "--text",
            secret_prefix + ("x" * MAX_TEXT_LENGTH),
        ]
    ) == 2
    error_output = capsys.readouterr().err
    assert secret_prefix not in error_output
    assert "exceeds" in error_output


def test_current_revision_rows_are_returned_by_default(tmp_path: Path) -> None:
    _settings, _paths, engine = _runtime(tmp_path)
    try:
        with session_scope(engine) as session:
            service = ContextService(session)
            first = service.add(
                text="Synthetic v1",
                temporal=parse_date_only("2026-09-22"),
                operation_id="head-add",
            )
            second = service.revise(
                first.event_id,
                text="Synthetic v2",
                operation_id="head-revise",
            )
            current_rows = tuple(session.scalars(select(ContextEventRevision)))
            assert len(current_rows) == 2
            assert service.list()[0].revision_id == second.revision_id
    finally:
        engine.dispose()
