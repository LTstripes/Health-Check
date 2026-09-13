"""Privacy-safe offline diagnosis of persisted Google terminal evidence."""

from __future__ import annotations

import json

import pytest

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import GooglePayloadStatus
from healthcheck.google.contracts import (
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
)
from healthcheck.google.diagnostics import diagnose_latest_invalid_google_envelope
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.google.sync import classify_page_envelope_structure
from healthcheck.runtime import prepare_runtime


@pytest.fixture
def persisted_invalid_envelope(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    store = ContentAddressedGooglePayloadStore(paths.root / "artifacts")
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            GooglePersistenceRepository(session, payload_store=store).persist_observation(
                identity=GoogleSourceIdentity(
                    source_kind=GoogleSourceKind.DATA_SOURCE,
                    source_instance_id="synthetic-google-source",
                ),
                query=GoogleQueryContext(query_mode=GoogleQueryMode.LIST),
                stream=GoogleStream.HEART_RATE,
                payload={"dataPoints": None},
                parse_status=GooglePayloadStatus.INVALID,
                records=(),
            )
            session.commit()
        yield settings, paths
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("payload", "presence", "collection_type", "parser_kind"),
    [
        ({}, "missing", "absent", "complete"),
        ({"dataPoints": None}, "present", "null", "invalid"),
        ({"dataPoints": {}}, "present", "object", "invalid"),
    ],
)
def test_page_envelope_structure_reports_only_safe_categories(
    payload, presence, collection_type, parser_kind
) -> None:
    structure = classify_page_envelope_structure(payload, GoogleQueryMode.LIST)

    assert structure.collection_presence == presence
    assert structure.collection_type == collection_type
    assert structure.next_page_token_type == "absent"
    assert structure.parser_kind == parser_kind


def test_missing_collection_stays_invalid_for_rollup_pages() -> None:
    structure = classify_page_envelope_structure({}, "rollUp")

    assert structure.collection_type == "absent"
    assert structure.parser_kind == "invalid"


def test_unknown_sibling_fields_do_not_become_empty_terminal_pages() -> None:
    structure = classify_page_envelope_structure({"unexpected": True}, "list")

    assert structure.collection_type == "absent"
    assert structure.parser_kind == "invalid"


def test_persisted_invalid_envelope_is_diagnosed_without_exposure(
    persisted_invalid_envelope, capfd
) -> None:
    settings, paths = persisted_invalid_envelope
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            diagnosis = diagnose_latest_invalid_google_envelope(
                session,
                payload_store=ContentAddressedGooglePayloadStore(paths.root / "artifacts"),
            )
    finally:
        engine.dispose()

    assert diagnosis.status == "diagnosed"
    assert diagnosis.stage == "page_envelope"
    assert diagnosis.diagnostic_code == "shape_drift_page_envelope_collection_null"
    assert diagnosis.collection_presence == "present"
    assert diagnosis.collection_type == "null"
    assert diagnosis.next_page_token_type == "absent"
    assert diagnosis.as_dict()["privacy"] == {
        "raw_values_emitted": False,
        "private_identifiers_emitted": False,
        "tokens_emitted": False,
        "health_timestamps_emitted": False,
        "page_tokens_emitted": False,
        "string_encoded_numerics_logged_as_values": False,
    }

    exit_code = cli.main(["google-diagnose-terminal", "--data-dir", str(settings.data_dir)])
    captured = capfd.readouterr()
    assert exit_code == 0
    output = json.loads(captured.out)
    assert output["diagnosis"]["diagnostic_code"] == "shape_drift_page_envelope_collection_null"
    assert "synthetic-google-source" not in captured.out
    assert '"dataPoints": null' not in captured.out
