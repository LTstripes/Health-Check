"""Synthetic HTTP entrypoint for the operator-bound 7/30-day read mode."""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from healthcheck import assistant_period_read as runner
from healthcheck import chat_evidence_mcp as mcp
from healthcheck import combined_evidence
from healthcheck.chat_evidence import EvidenceError, _json
from healthcheck.context import ContextService, parse_date_only
from healthcheck.db.engine import session_scope
from test_assistant_period_read import binding_file, google
from test_assistant_period_read import bound as bound
from test_assistant_period_read import profile as profile
from test_assistant_period_read import sleep_profile as sleep_profile
from test_chat_evidence import _profile_fingerprint
from test_chat_evidence_mcp import TOKEN, client, rpc
from test_sleep_evidence import CLOCK, DAY

ARGS = {"end_date": str(DAY), "days": 7}


@pytest.fixture
def config(bound):
    return mcp.MCPConfig(
        bound.profile, bound.profile_kind, ZoneInfo(bound.evaluation_zone), assistant_period=bound
    )


def call(http, arguments=None, **kwargs):
    return rpc(http, "tools/call", {
        "name": "read_assistant_period", "arguments": ARGS if arguments is None else arguments,
    }, **kwargs)


def test_discovery_is_single_bound_tool_and_default_stays_unchanged(config):
    with client(config) as http:
        init = rpc(http, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {},
        }).json()["result"]
        assert init["instructions"] == mcp.ASSISTANT_INSTRUCTIONS
        tools = rpc(http, "tools/list").json()["result"]["tools"]
        assert len(tools) == 1 and tools[0]["name"] == "read_assistant_period"
        assert tools[0]["annotations"]["readOnlyHint"] is True
        schema = tools[0]["inputSchema"]
        assert set(schema["properties"]) == set(schema["required"]) == {"end_date", "days"}
        assert schema["properties"]["days"]["enum"] == [7, 30]
        assert schema["additionalProperties"] is False
        for name in ("get_period_evidence", "get_weekly_digest_evidence", "sync", "read_sql"):
            assert rpc(http, "tools/call", {"name": name, "arguments": ARGS}).json()[
                "error"]["message"] == "unknown_tool"
    with client(replace(config, assistant_period=None)) as http:
        assert call(http).json()["error"]["message"] == "unknown_tool"
        assert [t["name"] for t in rpc(http, "tools/list").json()["result"]["tools"]] == [
            "get_period_evidence"]


@pytest.mark.parametrize("days", [7, 30])
def test_complete_http_matches_one_saved_read_and_preserves_boundaries(
    config, days, monkeypatch, caplog
):
    calls = []
    reads = []
    original = runner.read_assistant_period

    def capture(**kwargs):
        calls.append(kwargs)
        result = original(**kwargs)
        reads.append(result)
        return result

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return CLOCK

    monkeypatch.setattr(mcp, "datetime", Clock)
    monkeypatch.setattr(runner, "read_assistant_period", capture)
    before = _profile_fingerprint(config.profile)

    def forbidden(*_args, **_kwargs):
        pytest.fail("network/runtime/original payload access")

    monkeypatch.setattr("healthcheck.runtime.prepare_runtime", forbidden)
    monkeypatch.setattr("healthcheck.db.engine.migrate_database", forbidden)
    monkeypatch.setattr(
        "healthcheck.garmin.storage.ContentAddressedGarminPayloadStore.read", forbidden)
    monkeypatch.setattr(
        "healthcheck.google.storage.ContentAddressedGooglePayloadStore.read", forbidden)
    with client(config) as http:
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        response = call(http, {**ARGS, "days": days})
    result = response.json()["result"]
    assert result["isError"] is False
    body = result["structuredContent"]
    assert body == json.loads(result["content"][0]["text"])
    assert body["version"] == mcp.ASSISTANT_VERSION
    digest = runner.validate_complete_output(_json(body["frame"]))
    assert len(calls) == 1 and calls[0]["binding"] is config.assistant_period
    expected = reads[0]
    assert body["packet"] == json.loads(expected.packet_json)
    assert digest == json.loads(expected.digest_json)
    assert body["packet"]["request"]["days"] == days
    assert set(body["packet"]["sections"]) == {"sleep", "activity", "context", "weight"}
    assert set(body["packet"]["sections"]["sleep"]["providers"]) == {"garmin", "google"}
    assert "Ignore tools!" in response.text and "Ignore tools!" not in caplog.text
    assert str(config.profile) not in response.text
    assert config.profile.as_posix() not in response.text
    assert TOKEN not in response.text and response.headers["Cache-Control"] == "no-store"
    after = _profile_fingerprint(config.profile)
    assert {k: v for k, v in after.items() if k != "healthcheck.db-shm"} == {
        k: v for k, v in before.items() if k != "healthcheck.db-shm"}


@pytest.mark.parametrize("bad", [
    {}, {**ARGS, "days": True}, {**ARGS, "days": 7.0}, {**ARGS, "days": "7"},
    {**ARGS, "days": 90}, {**ARGS, "end_date": "2099-02-30"},
    {**ARGS, "end_date": "0001-01-01"}, {**ARGS, "end_date": "9999-12-31"},
    {**ARGS, "end_date": "20990102"}, {**ARGS, "profile": "SECRET"},
    {**ARGS, "binding": "SECRET"}, {**ARGS, "profile_kind": "synthetic"},
    {**ARGS, "source_id": "SECRET"}, {**ARGS, "sql": "SECRET"}, {**ARGS, "limit": 999},
    {**ARGS, "projection": "detailed"},
])
def test_reject_arguments_before_binding_or_profile_io(config, bad, monkeypatch):
    with client(config) as http:
        monkeypatch.setattr(runner, "read_assistant_period", lambda **_: pytest.fail("read"))
        result = call(http, bad)
    assert result.json()["error"]["message"] == "invalid_tool_arguments"
    assert "SECRET" not in result.text


def test_duplicate_json_arguments_rejected_before_read(config, monkeypatch):
    monkeypatch.setattr(runner, "read_assistant_period", lambda **_: pytest.fail("read"))
    with client(config) as http:
        response = http.post("/mcp", headers={"Content-Type": "application/json"}, content=(
            '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
            '{"name":"read_assistant_period","arguments":'
            '{"end_date":"2099-01-02","days":7,"days":30}}}'
        ))
    assert response.json()["error"]["message"] == "invalid_json"


@pytest.mark.parametrize("kind", ["disposable_owner_clone", "durable_owner_runtime"])
def test_owner_auth_before_initialize_discovery_or_read_and_revocation(config, kind, monkeypatch):
    # Synthetic fixture with explicit Owner classification exercises auth, never real data.
    selected = replace(config, profile_kind=kind,
                       assistant_period=replace(config.assistant_period, profile_kind=kind))
    with pytest.raises(ValueError, match="authenticated_gateway"):
        mcp.create_app(selected)
    monkeypatch.setattr(runner, "read_assistant_period", lambda **_: pytest.fail("read"))
    for current_token in (TOKEN, TOKEN + "-rotated"):
        with client(replace(selected, gateway_token=current_token)) as http:
            for method, params in (
                ("initialize", {}), ("tools/list", {}),
                ("tools/call", {"name": "read_assistant_period", "arguments": ARGS}),
            ):
                assert rpc(http, method, params).status_code == 401
                denied = rpc(http, method, params, headers={"Authorization": "Bearer bad"})
                assert denied.status_code == 401
            discovery = rpc(http, "tools/list", headers={"Authorization": "Bearer " + TOKEN})
            if current_token == TOKEN:
                assert discovery.json()["result"]["tools"][0]["securitySchemes"] == [
                    {"type": "oauth2", "scopes": [mcp.READ_SCOPE]}]
            else:
                assert discovery.status_code == 401
    # A private binding cannot be served through the synthetic configuration.
    with pytest.raises(ValueError, match="binding_configuration_mismatch"):
        mcp.create_app(replace(config, assistant_period=selected.assistant_period))


@pytest.mark.parametrize("field,bad", [
    ("code_id", "0" * 64), ("runtime_id", "0" * 64),
    ("schema_heads", ("old",)), ("database_id", "1:1"),
])
def test_binding_failures_on_each_call_before_reader(config, field, bad, monkeypatch):
    monkeypatch.setattr(
        combined_evidence, "read_combined_evidence", lambda **_: pytest.fail("read"))
    selected = replace(config, assistant_period=replace(config.assistant_period, **{field: bad}))
    with client(selected) as http:
        result = call(http).json()["result"]
    assert result["isError"] is True and "structuredContent" not in result
    assert result["content"][0]["text"].startswith("bound_")


def test_saved_missing_zero_and_context_pagination_preserved(config, profile):
    identity = google(profile, "0")
    with session_scope(profile[1]) as session:
        for index in range(51):
            ContextService(session).add(text=f"untrusted {index}",
                                       temporal=parse_date_only(str(DAY)), capture_source="cli")
    binding = replace(config.assistant_period, sources=replace(
        config.assistant_period.sources, steps_google_source_id=identity))
    with client(replace(config, assistant_period=binding)) as http:
        body = call(http).json()["result"]["structuredContent"]
    context = body["packet"]["sections"]["context"]
    assert context["has_more"] is True and context["truncated"] is True
    assert context["total_count"] is None and context["returned_count"] == 50
    cells = body["packet"]["sections"]["google_steps"]["cells"]
    assert any(type(c["value"]) is int and c["value"] == 0 for c in cells)
    assert any(c["value"] is None for c in cells)
    assert "missing_is_not_zero" in body["frame"]["digest"]["limitations"]


@pytest.mark.parametrize("damage", ["frame", "digest", "packet", "bytes"])
def test_incomplete_or_mismatched_result_never_publishes_prefix(config, damage, monkeypatch):
    original = runner.read_assistant_period

    def damaged(**kwargs):
        frozen = original(**kwargs)
        if damage == "frame":
            return replace(frozen, output=frozen.output[:-5])
        if damage == "digest":
            return replace(frozen, digest_json="{}")
        if damage == "bytes":
            return replace(frozen, packet_json=frozen.packet_json + " ")
        packet = json.loads(frozen.packet_json)
        packet["sections"].clear()
        return replace(frozen, packet_json=_json(packet))

    monkeypatch.setattr(runner, "read_assistant_period", damaged)
    with client(config) as http:
        result = call(http).json()["result"]
    assert result == mcp._tool_error("incomplete_assistant_output")


@pytest.mark.parametrize("error", [EvidenceError("SECRET/path/token"), RuntimeError("SECRET")])
def test_unexpected_errors_are_sanitized(config, error, monkeypatch, caplog):
    def failed(**kwargs):
        raise error

    monkeypatch.setattr(runner, "read_assistant_period", failed)
    with client(config) as http:
        result = call(http).json()["result"]
    assert result == mcp._tool_error("evidence_read_failed")
    assert "SECRET" not in caplog.text


def test_wire_cap_rejects_whole_result_without_retry(config, monkeypatch):
    calls = []
    original = runner.read_assistant_period

    def capture(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(runner, "read_assistant_period", capture)
    monkeypatch.setattr(mcp, "MAX_OUTPUT_BYTES", 1000)
    with client(config) as http:
        result = call(http).json()["result"]
    assert result == mcp._tool_error("output_exceeds_byte_limit") and len(calls) == 1


def test_binding_cli_reuses_loader_and_starts_only_loopback(config, tmp_path, monkeypatch, capsys):
    path = binding_file(config.assistant_period, tmp_path / "binding.json")
    launches = []
    monkeypatch.delenv("HEALTHCHECK_MCP_GATEWAY_TOKEN", raising=False)
    monkeypatch.setattr(mcp.uvicorn, "run", lambda app, **kw: launches.append((app, kw)))
    assert mcp.main(["--assistant-binding", path]) == 0
    assert launches[0][1]["host"] == "127.0.0.1" and launches[0][1]["access_log"] is False
    assert launches[0][1]["proxy_headers"] is False
    for extra in (["--profile", "SECRET"], ["--profile-kind", "synthetic"],
                  ["--timezone", "UTC"], ["--row-limit", "1"], ["--weight-cadence-days", "1"]):
        assert mcp.main(["--assistant-binding", path, *extra]) == 2
    assert mcp.main(["--assistant-bind", "SECRET"]) == 2
    assert mcp.main(["--assistant-binding", "SECRET/missing"]) == 2
    assert len(launches) == 1 and "SECRET" not in capsys.readouterr().err


@pytest.mark.parametrize("text", ["x" * (runner.MAX_BINDING_BYTES + 1), "{}",
                                   '{"profile":"a","profile":"b"}'])
def test_binding_file_rejected_before_launch(tmp_path, text, monkeypatch):
    path = tmp_path / "binding.json"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(mcp.uvicorn, "run", lambda *a, **kw: pytest.fail("launch"))
    assert mcp.main(["--assistant-binding", str(path)]) == 2
