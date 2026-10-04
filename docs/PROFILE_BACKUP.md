# Local profile backup and restore

Health-Check keeps the local profile outside the checkout. The CLI can make a
portable backup before private data is added, verify it, and restore it into a
new profile.

```powershell
uv run healthcheck backup-profile --data-dir C:\Temp\Health-Check-demo `
  --output C:\Backups\health-check-profile.zip
uv run healthcheck verify-backup --backup C:\Backups\health-check-profile.zip
uv run healthcheck restore-profile --backup C:\Backups\health-check-profile.zip `
  --target-dir C:\Temp\Health-Check-restored
```

The source profile must be a real directory outside the checkout. The archive
destination and restore target must also be outside the checkout, and their
paths may not be the checkout or one of its ancestor directories, and their
existing parent directories must be real directories. Existing non-empty
restore targets are refused. A normal restore into a non-empty target is not
allowed; an empty/new target is preferred. The explicit `--replace` option is
required for a non-empty target and atomically swaps the validated target. It
removes that target only after the complete archive, checksum, SQLite and path
preflight has succeeded.

An attempted normal restore into a non-empty target is refused and leaves all
unknown owner files untouched. Replace is the explicit exception: it replaces
the complete target after checking that every existing entry is a regular file
or directory and contains no links or special files. A failed swap restores the
old target.

The archive contains `healthcheck.db`, `config.toml` when present, the
`artifacts/` tree and other regular profile files. The `logs/` directory is
excluded as transient material. SQLite is copied with the SQLite Online Backup
API while WAL is active; `-wal` and `-shm` sidecars are not archived. The
manifest records format/app/schema identity, creation time, synthetic/normal
classification, database consistency method and a SHA-256 checksum for every
archived file.

Verification rejects malformed or incomplete manifests, checksum changes,
duplicate/extra entries, traversal paths, absolute paths, ZIP symlinks and
special files, oversized members, and databases that fail integrity or
migration-identity checks. Commands print only status, counts and classification;
they never print profile file contents, measurements or secrets.

Protected filesystem publication, retention and clean disaster recovery are documented in
[Off-site backup v1](OFFSITE_BACKUP.md). Format v1 remains ZIP64-compatible and accepts a
maximum expanded size of 16 GiB per member and 20 GiB total. Backup creation checks the
staged SQLite-consistent file sizes against these bounds before writing the ZIP.

## Targeted synthetic checks

For everyday WAL or backup iterations, use external synthetic runtime/temp paths
and the existing tests. These selections are targeted checks, not the complete CI:

```powershell
$probe = Join-Path ([System.IO.Path]::GetTempPath()) ("healthcheck-backup-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $probe | Out-Null
$env:HEALTHCHECK_DATA_DIR = Join-Path $probe "runtime"
$env:TEMP = $probe
$env:TMP = $probe
uv run --locked pytest tests/test_profile_backup.py -k wal `
  --basetemp (Join-Path $probe "pytest-wal") --durations=5
uv run --locked pytest tests/test_profile_backup.py -k "not large_sparse" `
  --basetemp (Join-Path $probe "pytest-small") --durations=5
```

The WAL fixture checkpoints only the empty marker table, then pins a reader's
pre-insert snapshot and holds the writer open after committing the marker. At
the `create_backup` boundary, a normal read sees the marker while an immutable
main-DB-only read sees an intact empty table. Both connections close on failure
as well as success. The small positive test uses the real `create_backup`,
`verify_backup` and `restore_profile`, checks sidecar exclusion and restored
integrity/content. A separate negative test substitutes an intentionally wrong
main-DB-only copy: real verification/restore still succeed, but the same restored
marker assertion detects the lost committed WAL record.

The >1 GiB zeroblob scenario remains in the ordinary complete CI, with unchanged
source/restored size thresholds, payload/marker assertions and integrity checks.
It retains the test-only `_fast_online_backup`: this is large-file evidence with
a tuned copy, not an unchanged production backup round-trip. Compared with
production `_online_backup`, its only behavioral difference is the SQLite backup
call (`pages=0, sleep=0` instead of `pages=100, sleep=0.05`). Source/destination
integrity checks and the real archive creation, verification and restore remain.
[CPython 3.12.14's implementation](https://github.com/python/cpython/blob/v3.12.14/Modules/_sqlite/connection.c#L2100-L2106)
sleeps on `SQLITE_BUSY`/`SQLITE_LOCKED`, not after each successful page batch.
This sparse/compressible synthetic test proves large-file recovery, not private
profile performance or behavior under concurrent writer contention.

The bounded #275 assessment on Windows / Python 3.12.14 / SQLite 3.53.1 observed
84.37 s call with the helper and 93.25 s with production in the same large test.
An isolated comparison on one 1,201,188,864-byte synthetic DB measured the whole
`_online_backup` stage (including its integrity checks): production 21.24 s, then
the baseline helper 6.71 s. These are single observations in a fixed order, not
a portable speed guarantee or a contention benchmark. The observed additional
cost supports retaining the tuned large test and using the small WAL test for
unmodified production-path evidence; no production pacing or CI routing changed.

Run that large test locally only to answer a concrete large-file/production-path
question; otherwise reuse the required exact-candidate complete CI:

```powershell
uv run --locked pytest tests/test_profile_backup.py::test_large_sparse_profile_above_one_gib_backup_verify_restore `
  --basetemp (Join-Path $probe "pytest-large") --durations=1
```
