"""Read-only measurement on a closed, checkpointed database COPY; never migrate.

Usage: uv run --locked python scripts/google_projection_dry_run.py --db-copy COPY --samples 48
The first N attempts in id order are sampled; this is not a statistical estimate.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from healthcheck.google.projection_storage import compress_projection, read_projection


def measure(database: Path, samples: int) -> dict[str, object]:
    database = database.resolve(strict=True)
    if samples <= 0:
        raise ValueError("positive sample count required")
    # Immutable avoids even creating SHM/WAL files. Refuse outstanding WAL
    # rather than silently measuring a stale main file with immutable=1.
    if any(path.exists() and path.stat().st_size for path in (
        Path(str(database) + "-wal"), Path(str(database) + "-journal"),
    )):
        raise ValueError("closed checkpointed DB copy required")
    raw_bytes = compressed_bytes = verified = failed = 0
    with closing(sqlite3.connect(
        database.as_uri() + "?mode=ro&immutable=1", uri=True,
    )) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(google_normalization_attempts)"
        )}
        names = [name for name in (
            "projection_json", "projection_fingerprint", "projection_blob",
            "projection_codec", "projection_size", "projection_sha256",
        ) if name in columns]
        query = (f"SELECT {', '.join(names)} FROM google_normalization_attempts "
                 "ORDER BY id LIMIT ?")
        for row in connection.execute(query, (samples,)):
            try:
                projection = read_projection(dict(row))
                compressed = compress_projection(projection, row["projection_fingerprint"])
                raw_bytes += len(projection.encode("utf-8"))
                compressed_bytes += len(compressed["projection_blob"])
                verified += 1
            except ValueError:
                failed += 1
    return {
        "sampled": verified + failed, "verified": verified, "failed": failed,
        "uncompressed_bytes": raw_bytes, "zlib_level_1_bytes": compressed_bytes,
        "compressed_to_uncompressed": compressed_bytes / raw_bytes if raw_bytes else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-copy", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=48)
    args = parser.parse_args()
    try:
        result = measure(args.db_copy, args.samples)
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({"error": "Google projection dry run failed"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return int(result["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
