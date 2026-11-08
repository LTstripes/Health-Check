"""Optional deterministic, function-grouped test sharding for CI."""

import os
import re
import zlib

import pytest


def parse_test_shard(value: str) -> tuple[int, int]:
    """Return a validated one-based shard index and shard count."""
    if not re.fullmatch(r"[0-9]+/[0-9]+", value):
        raise pytest.UsageError("HEALTHCHECK_TEST_SHARD must be i/n with 1 <= i <= n")
    index, count = map(int, value.split("/"))
    if not 1 <= index <= count:
        raise pytest.UsageError("HEALTHCHECK_TEST_SHARD must be i/n with 1 <= i <= n")
    return index, count


def shard_for_nodeid(nodeid: str, count: int) -> int:
    """Keep all parameter cases of a function on the same one-based shard."""
    group = nodeid.split("[", 1)[0]
    return zlib.crc32(group.encode("utf-8")) % count + 1


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    value = os.environ.get("HEALTHCHECK_TEST_SHARD")
    if value is None:
        return
    index, count = parse_test_shard(value)
    kept, deselected = [], []
    for item in items:
        (kept if shard_for_nodeid(item.nodeid, count) == index else deselected).append(item)
    items[:] = kept
    config.hook.pytest_deselected(items=deselected)
