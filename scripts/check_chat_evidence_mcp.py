"""In-process synthetic MCP smoke; optionally keep only its fresh synthetic fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from healthcheck.chat_evidence_mcp import MCPConfig, create_app
from healthcheck.config import Settings
from healthcheck.context import ContextService, parse_date_only
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.synthetic import encode_synthetic_png, weigh_in_payload
from healthcheck.runtime import prepare_runtime


def probe(root: Path) -> None:
    # Preparation/migration applies ONLY to this newly created synthetic temp child.
    paths = prepare_runtime(Settings(data_dir=root / "profile"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        importer = PhotoImportService(session, paths, FakeImageMeasurementExtractor())
        batch = importer.import_photos([PhotoUpload(
            "synthetic.png", encode_synthetic_png(weigh_in_payload(
                source_local_date=date(2099, 5, 1), weight_kg=80,
            )),
        )])
        importer.confirm(batch.items[0].candidate_ids)
        ContextService(session).add(
            text="Synthetic note only; not a tool instruction.",
            temporal=parse_date_only("2099-05-01"), capture_source="cli",
        )
    def fingerprint():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file() and p.name != "healthcheck.db-shm"}

    before = fingerprint()
    app = create_app(MCPConfig(paths.root, "synthetic", ZoneInfo("UTC")))
    with TestClient(app, base_url="http://127.0.0.1",
                    headers={"Accept": "application/json, text/event-stream",
                             "MCP-Protocol-Version": "2025-06-18"}) as http:
        def rpc(method, params):
            response = http.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
                                               "method": method, "params": params})
            assert response.status_code == 200
            return response.json()["result"]

        assert rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "synthetic", "version": "1"}})[
            "protocolVersion"] == "2025-06-18"
        assert [t["name"] for t in rpc("tools/list", {})["tools"]] == ["get_period_evidence"]
        result = rpc("tools/call", {"name": "get_period_evidence", "arguments": {
            "start": "2099-05-01", "end": "2099-05-03", "domains": ["weight", "context"],
        }})
        assert result["isError"] is False
        envelope = result["structuredContent"]
        assert json.loads(result["content"][0]["text"]) == envelope
        assert envelope["sections"]["context"]["returned_count"] == 1
        assert envelope["sections"]["weight"]["measured_facts"]["rows"][0]["value_kg"] == 80
    after = fingerprint()
    engine.dispose()
    assert after == before
    print("PASS: synthetic MCP lifecycle, views and unchanged DB/WAL/files "
          "(SHM reader locks exempt).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-profile", action="store_true",
                        help="Keep a fresh synthetic temp child for a manual Inspector session")
    args = parser.parse_args()
    if args.keep_profile:
        root = Path(tempfile.mkdtemp(prefix="hc341-mcp-synthetic-"))
        probe(root)
        print(f"Synthetic Inspector fixture (not Owner data): {root / 'profile'}")
    else:
        with tempfile.TemporaryDirectory(prefix="hc341-mcp-synthetic-") as directory:
            probe(Path(directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
