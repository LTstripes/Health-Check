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
