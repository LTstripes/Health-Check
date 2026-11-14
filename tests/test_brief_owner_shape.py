"""Frozen a77ce66c oracle, dense synthetic shape and full route equivalence."""

import importlib
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from scripts.brief_owner_shape import generate_owner_shape
from scripts.profile_brief import parse_timing

from healthcheck.config import Settings
from healthcheck.web import pages, period_brief_query
from healthcheck.web.ui_app import create_ui_app


@contextmanager
def baseline_readers():
    reference = json.loads((Path(__file__).parents[1] / "scripts"
                            / "brief_owner_shape_reference.json").read_text(encoding="utf-8"))
    patches = []
    try:
        for entry in reference["functions"]:
            module = importlib.import_module(entry["module"])
            owner = module
            parts = entry["name"].split(".")
            for part in parts[:-1]:
                owner = getattr(owner, part)
            original = getattr(owner, parts[-1])
            namespace = {}
            exec(compile(entry["source"], "<frozen-a77ce66c>", "exec"),
                 module.__dict__, namespace)
            frozen = namespace[parts[-1]]
            targets = [(owner, parts[-1])]
            if owner is module:
                targets.extend((item, name) for item in list(sys.modules.values())
                               if item and getattr(item, "__name__", "").startswith("healthcheck.")
                               for name, value in list(vars(item).items())
                               if value is original and (item, name) not in targets)
            for target, name in targets:
                replacement = patch.object(target, name, frozen)
                replacement.start()
                patches.append(replacement)
        yield
    finally:
        for replacement in reversed(patches):
            replacement.stop()


@pytest.fixture(scope="module")
def owner_shape(tmp_path_factory):
    root = tmp_path_factory.mktemp("shape") / "profile"
    return root, generate_owner_shape(root, scale=.005)


@pytest.mark.parametrize("empty", [False, True])
def test_entire_brief_context_and_comparison_match_frozen_baseline(owner_shape, monkeypatch, empty):
    root, manifest = owner_shape

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 11, 12, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(pages, "datetime", Clock)
    monkeypatch.setattr(period_brief_query, "datetime", Clock)
    app, _ = create_ui_app(Settings(data_dir=root))
    params = {"start_date": "2000-01-01" if empty else "2026-09-11",
              "end_date": "2000-01-30" if empty else "2026-10-10",
              "garmin_source_id": manifest["garmin_source_id"]}
    client = TestClient(app, base_url="http://127.0.0.1:8120")
    try:
        with baseline_readers():
            before = client.get("/brief", params=params)
        after = client.get("/brief", params=params)
        assert before.status_code == after.status_code == 200
        # Request objects and template helper identities are framework inputs;
        # compare every other context field, retaining timestamps and hashes.
        def content(response):
            return {key: value for key, value in response.context.items()
                    if key != "request" and not callable(value)}

        assert content(after) == content(before)
        assert after.context["overview"]["comparison"] == before.context["overview"]["comparison"]
        assert after.text == before.text
        if not empty:
            overview = after.context["overview"]
            assert overview["period_sleep"]["mean_value"] is not None
            assert overview["training"]["status"] == "available"
            assert manifest["counts"]["google_record_metrics"] > 13000
            assert parse_timing(after.headers["Server-Timing"])["overview_queries"] < (
                parse_timing(before.headers["Server-Timing"])["overview_queries"])
    finally:
        client.close()
