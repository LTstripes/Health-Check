"""Contracts for the optional CI collection selector."""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from conftest import parse_test_shard, pytest_collection_modifyitems
from conftest import shard_for_nodeid as shard_for


@pytest.mark.parametrize("value, expected", [("1/1", (1, 1)), ("2/3", (2, 3)), ("3/3", (3, 3))])
def test_parse_valid(value, expected):
    assert parse_test_shard(value) == expected


@pytest.mark.parametrize("value", ["0/3", "4/3", "a/b", "3", "1/0", " ", " 1/3", "1/3 ",
                                   "", "1 /3", "1/ 3", "-1/3", "1/3\n", "1/2/3"])
def test_parse_invalid(value):
    with pytest.raises(pytest.UsageError):
        parse_test_shard(value)


def test_collection_partition(monkeypatch):
    nodeids = ["a.py::test_a[x]", "a.py::test_a[y]", "a.py::C::test_b", "b.py::test_c"]
    items = [SimpleNamespace(nodeid=nodeid) for nodeid in nodeids]
    partitions = []
    for index in range(1, 4):
        monkeypatch.setenv("HEALTHCHECK_TEST_SHARD", f"{index}/3")
        deselected = []
        config = SimpleNamespace(hook=SimpleNamespace(
            pytest_deselected=lambda items: deselected.extend(items)))
        selected = items.copy()
        pytest_collection_modifyitems(config, selected)
        assert selected == [item for item in items if item not in deselected]
        assert len(selected) + len(deselected) == len(items)
        partitions.append({item.nodeid for item in selected})
    assert set.union(*partitions) == set(nodeids)
    assert sum(map(len, partitions)) == len(nodeids)
    assert any(set(nodeids[:2]) <= part for part in partitions)


def test_unset_leaves_collection_unchanged(monkeypatch):
    monkeypatch.delenv("HEALTHCHECK_TEST_SHARD", raising=False)
    items = [object(), object()]
    original = items.copy()
    pytest_collection_modifyitems(None, items)
    assert items == original


def test_deterministic_across_processes():
    nodeid = "tests/example.py::Example::test_unicode_é[param]"
    code = f"from conftest import shard_for_nodeid; print(shard_for_nodeid({nodeid!r}, 3))"
    for seed in ("1", "98765"):
        result = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True,
                                text=True, env={**os.environ, "PYTHONHASHSEED": seed})
        assert int(result.stdout.strip()) == shard_for(nodeid, 3)
