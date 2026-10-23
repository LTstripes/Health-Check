<a id="book--owner-operations"></a>
# Owner Operations

This book owns complete operational procedures. Follow the active authorization
before running a mutating command. Examples do not authorize refresh, migration,
restore, scheduler changes, auth, import, cleanup, deployment or publication.
Use accepted code and explicit external profiles; preserve Stable and verify
bindings. Technical source/envelope meanings are in Architecture.

| Operation | Start here | Required boundary |
| --- | --- | --- |
| Inspect relevant saved Owner evidence | [Owner data](#owner-data-boundary) | Assigned read scope; no migration-capable startup |
| Prepare/recover a profile | [Backup/restore](#profile-backup), [offsite](#offsite-backup) | Verified supported backup, explicit target, applicable write authority |
| Refresh/backfill/auth | [Refresh](#refresh), [Garmin](#garmin-auth) | Exact provider/date/stream scope and idle selected writer |
| Import Weight screenshot | [Screenshot workflow](#screenshot-import) | Trusted original, exact metadata, review and authorized confirmation |
| Export saved evidence | [Analysis export](#analysis-export) | Explicit source/profile/window and read-only evidence boundary |
| Run MCP | [MCP service](#mcp-service) | Explicit existing profile, host/auth/connection decision |
| Use or retire a task checkout | [Lifecycle](#workspace-lifecycle), [v2 retirement](#workspace-retirement) | Actual accepted installed consumer, current claim and separate cleanup authority |


<a id="owner-data-boundary"></a>

<a id="owner-data-boundary--owner-data-access-writes-and-privacy"></a>
## Owner data access, writes and privacy

<a id="owner-data-boundary--owner-data-and-efficient-task-execution"></a>
## Owner data and efficient task execution

Owner decision: 2026-10-10. This is the standing workflow for Owner-requested analysis,
diagnosis and UAT; it clarifies earlier blanket restrictions on private-data visibility.

<a id="owner-data-boundary--data-access-and-presentation"></a>
### Data access and presentation

An Owner request to analyze, diagnose or visually verify their data authorizes the
assigned assistant to read the relevant real records, reports, documents, screenshots
and UI in the assigned context. Use ordinary local viewers, browser tools and model
vision/text in the authorized assistant conversation. Do not ask again for each
record, image or query. Values, dates, names, identifiers and local paths are not
credentials merely because they are personal. Show the facts needed to answer the
Owner without compulsory masking or opaque surrogate labels.

Keep real datasets and working reports in the assigned Owner-data location outside
the tracked code checkout. A code task that needs Owner evidence can perform an
authorized read-only diagnostic there; it need not pretend that all useful evidence
is synthetic. Automated tests/CI and committed examples still use synthetic data.
Do not copy or link runtime databases into code fixtures. Read-only database work
uses an appropriate read-only connection and must not run migration-capable startup.

Access credentials, tokens, recovery keys and real `.env` contents are not report
material. Do not print them. Public GitHub/CI publication and sharing to another
recipient are separate from showing relevant data to the Owner in the authorized
AI conversation. Ordinary task authorization is not permission to publish a whole
dataset; follow a specific Owner publication request when one is given.

<a id="owner-data-boundary--reads-runtime-changes-and-data-writes"></a>
### Reads, runtime changes and data writes

Reading/analyzing assigned data does not authorize database writes, migrations,
reimports, semantic attestations, production changes or destructive operations.
Those require the applicable task authority. Once the Owner has authorized a bounded
operation, carry out its necessary reversible steps without repeated consent.
Normal code checks do not call account-backed providers. Live provider operations,
runtime preparation/start/stop and external connections use their assigned scope.
Stable remains durable; candidate runtime validation uses an isolated approved clone.


<a id="offline-runtime-evidence"></a>

<a id="offline-runtime-evidence--offline-evidence-and-running-application-continuation"></a>
## Offline evidence and running-application continuation

<a id="offline-runtime-evidence--offline-evidence-and-runtime-continuation"></a>
### Offline evidence and runtime continuation

Declare whether the task reads saved evidence or evaluates a running application.
An offline clone audit needs code/clone/checkpoint identity and the required database
checks; it does not need a listener or running UI. Runtime verification additionally
needs a current process identity (PID plus creation time/executable), endpoint and
evidence binding the loaded code and selected data/profile. `/healthz`, a Git SHA,
an old PID or a matching filename alone does not establish that binding.

Keep a small local receipt of observed identity and completed steps with evidence
references. On continuation, validate only dependencies of the next step. Changed
code/data/process or modified evidence invalidates affected results; a new chat or
lost polling session alone does not. File hashes do not prove database integrity,
and process metadata does not prove application/profile binding. Preserve those
limits rather than rerunning unrelated work or claiming fresh success.


<a id="machine-layout"></a>

<a id="machine-layout--owner-machine-layout-and-path-roles"></a>
## Owner machine layout and path roles

Canonical local filesystem layout for the Owner Windows machine. This page owns the concrete Health-Check paths; other process documents should link here instead of duplicating absolute paths.

<a id="machine-layout--canonical-root"></a>
### Canonical root

```text
D:\HealthCheck\
  main\
  stable\
  uat\
  ops\
  workspaces\
    codex\
    opencode\
    grok\
    hermes\
```

| Path | Role | May agents implement here? |
| --- | --- | --- |
| `D:\HealthCheck\main` | Clean trusted checkout of canonical Git `main`; Owner/control operations | **No** |
| `D:\HealthCheck\stable` | Durable private Owner runtime/data | **Never** |
| `D:\HealthCheck\uat` | Disposable Owner-only UAT/recovery profiles | **No** |
| `D:\HealthCheck\ops` | Owner-local scheduler wrappers and operational files | Only when an explicit ops task authorizes it |
| `D:\HealthCheck\workspaces\codex` | Codex task workspaces | Yes, assigned task child only |
| `D:\HealthCheck\workspaces\opencode` | OpenCode task workspaces | Yes, assigned task child only |
| `D:\HealthCheck\workspaces\grok` | Grok task/review workspaces | Yes, assigned task child only |
| `D:\HealthCheck\workspaces\hermes` | Hermes task/review workspaces | Yes, assigned task child only |

There is no separate top-level review tree. A Reviewer uses its own assigned child under the relevant client workspace root. Private product UAT belongs under `uat`, not under an agent workspace.

<a id="machine-layout--task-workspace-convention"></a>
### Task workspace convention

New work uses one physical workspace per task:

```text
D:\HealthCheck\workspaces\<client>\<issue-or-task>
```

Examples:

```text
D:\HealthCheck\workspaces\codex\256-workspace-janitor
D:\HealthCheck\workspaces\opencode\240-owner-screenshot-metadata
D:\HealthCheck\workspaces\grok\238-security-review
```

The task assignment must state the exact workspace when writes are authorized. A Worker may create/prepare that assigned child, but must not inspect, move, reuse or delete sibling task directories unless the task explicitly authorizes workspace maintenance.

Do not implement by switching branches in `main`. Never place real Owner health data, backups, credentials or provider state in `workspaces`.

<a id="machine-layout--ownerruntime-rules"></a>
### Owner/runtime rules

- `main` is code/control only. Keep it clean and fast-forward it only through the accepted Owner/Integrator flow.
- `stable` is the canonical private profile. Do not reset, repurpose or attach it to Worker branches.
- `uat` is disposable. Create private UAT/recovery state through supported backup/restore rather than copying or mutating Stable ad hoc.
- `ops` contains local operational wrappers. The Windows task `Health-Check owner refresh` uses this root and targets the canonical `main` + `stable` paths.
- Agent client defaults should point new Health-Check work at their matching `workspaces\<client>` root.

<a id="machine-layout--workspace-lifecycle-and-cleanup"></a>
### Workspace lifecycle and cleanup

Task workspaces are disposable after delivery. The historical #256 deployment used Windows Scheduled Task `Health-Check workspace cleanup`:

- runs **daily at 12:00 local time** with `StartWhenAvailable` and `IgnoreNew`;
- uses `-Apply -RetentionDays 7`;
- writes the latest bounded sanitized report to `D:\HealthCheck\ops\workspace-cleanup-latest.json`;
- considers only immediate task children under the four canonical `workspaces\<client>` roots;
- used the then-accepted Git, age, process and private-material guards.

This source description is not a live task read-back or authorization to register/enable it. The current source adds the [managed lifecycle contract](#workspace-lifecycle): only explicitly completed enrolled standalone clones may reach fetch/deletion. Retention is at least seven days since both completion and file/commit activity. Active, paused, legacy/unknown claims and all shared worktrees are preserved. Installing the matching helper/janitor pair and any scheduler change require separate acceptance; historical Apply is superseded and refused by current v2.

The janitor must never treat `main`, `stable`, `uat`, `ops` or a path outside the four approved workspace roots as a cleanup root. Unknown, active, young, wrong-origin or otherwise ambiguous task directories are preserved.

Do not manually drag active Git worktrees between roots. Let an active task finish in its assigned location, then let the janitor retire it or recreate it safely.

<a id="machine-layout--legacy-locations-and-path-changes"></a>
### Legacy locations and path changes

Legacy roots are not new task assignments and are outside automatic cleanup.
An old path existing on disk does not make it canonical. Historical inventories
and reclaim observations are retained by the original baseline permalink in the
migration receipt. Manual removal needs current process/reference and private
evidence disposition; an old READY verdict is not current deletion authority.
Update this central path-role chapter first when assignments change, then the
few operational consumers that encode them. Do not duplicate the table in prompts.

<a id="bootstrap"></a>

<a id="bootstrap--local-setup-and-first-synthetic-start"></a>
## Local setup and first synthetic start

<a id="bootstrap--local-bootstrap"></a>
### Local bootstrap

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

Use a fresh external directory and the marked synthetic seed. The examples below
write only that explicitly selected demo; they contain no provider login/refresh.

```powershell
uv sync --locked
$syntheticData = Join-Path ([System.IO.Path]::GetTempPath()) ("healthcheck-demo-" + [guid]::NewGuid())
$env:HEALTHCHECK_DATA_DIR = $syntheticData
uv run --locked python -m healthcheck.cli seed-demo
.\scripts\start.ps1 -DataDir $syntheticData -Port 8126
```

Open `http://127.0.0.1:8126/`. The persisted seed marker, not the directory's name,
establishes the synthetic-demo identity. Use the [synthetic demo chapter](DEVELOPMENT_PROCESS.md#synthetic-demo)
for its fixed data, guards and browser scenarios. Focused checks and an external
pytest temporary directory follow [verification by change](DEVELOPMENT_PROCESS.md#verification-by-change);
a manual full pytest run is not a bootstrap prerequisite.

Outside this explicitly bound demo, the launcher defaults to the normal `%LOCALAPPDATA%\Health-Check` when no `-DataDir` or `HEALTHCHECK_DATA_DIR` is supplied. Never use a bare launcher as a synthetic or read-only probe.
The startup script prepares/migrates its selected runtime; it is not a read-only
inspection command. Candidate UAT uses the explicitly verified disposable clone,
not Stable as a scratch target.

Normal Owner operation uses the protected code/data/UAT/Ops roles in [machine layout](#machine-layout). GitHub merges do not update the local checkout or restart its processes automatically.

[Owner Refresh](#refresh) documents the local selected-stream runner, Scheduler controls and unchanged bounded CLI. The command requires an already-established external runtime and does not create a new profile. Never switch/pull code while the Owner refresh or dependent application processes are using that checkout.

No health data, credentials, payloads, images, logs, database files or generated reports belong in the repository. Routine comments added to a disposable clone will not automatically become durable Stable notes; #294's real rollout must make the target explicit.


<a id="profile-backup"></a>

<a id="profile-backup--supported-local-profile-backup-and-restore"></a>
## Supported local profile backup and restore

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
[Off-site backup v1](#offsite-backup). Format v1 remains ZIP64-compatible and accepts a
maximum expanded size of 16 GiB per member and 20 GiB total. Backup creation checks the
staged SQLite-consistent file sizes against these bounds before writing the ZIP.

<a id="profile-backup--targeted-synthetic-checks"></a>
### Targeted synthetic checks

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

<a id="release-preflight-2026-10-22"></a>
## Release rehearsal, migration and rollback — 22 October 2026

[Wiki scope/release notes](PROJECT_WIKI.md#release-2026-10-22) and
[tracker #479](https://github.com/LTstripes/Health-Check/issues/479) own current status.
This is a prepared runbook. **No real-profile backup, restore, migration, Stable
deployment, provider request or release/tag publication was executed by this docs
task.** Operations below require an assignment with exact private paths. Examples
alone grant no authority.

The later separately authorized [technical rehearsal receipt](https://github.com/LTstripes/Health-Check/issues/479#issuecomment-6320839634)
records backup/verify/restore, copy-only migration/integrity/FK/artifact closure,
recovery and guarded offline UI PASS for candidate
`6c82874efa6494d5ad1d9d6e51f8d962050f8888`. That evidence remains specific to that
candidate. Temporary process guards altered outbound/decryption behavior and are
recorded in its provenance; the run was not unrestricted runtime or Owner UAT.
Original persistent-file fingerprints passed, while absence of the Stable process
was recorded separately; Stable was not started. A later audit correction does not
inherit an old candidate's code/UI result. The audit correction used synthetic
validation; this historical receipt does not authorize a new real-profile operation.
The #487/#489 quality corrections add no database migration or automatic raw/history
replay. The supported schema ancestry below is unchanged; this does not turn the
older candidate's runtime/UI rehearsal into a new-candidate pass.
The final targeted audit returned NO-GO for old code `303450b`. Its #484/#485
follow-up [#491](https://github.com/LTstripes/Health-Check/pull/491) completed exact
review/CI/post-main gates on canonical `430a11e`. A separately attributed
[Owner-supplied recheck](https://github.com/LTstripes/Health-Check/issues/479#issuecomment-6347157693)
reports both high findings CLOSED and 55 unique synthetic checks PASS, with GO
limited to isolated-copy preparation. That separately authorized preparation
completed on exact `430a11e`; its [technical receipt](https://github.com/LTstripes/Health-Check/issues/479#issuecomment-6348040813)
does not establish acceptance of the UI. The Owner ended UAT with UX NOT ACCEPTED;
release #479 remains NO-GO pending repeat acceptance of the corrected presentation.
The approved primary UX slices are now engineering accepted through #496, #497
and #498: product-code baseline `c1295b69e16be62d20b4e2a6d491d756a35e8302`,
tree `7c80ea0c96df90029439360d0edfa038b27afba8`; [latest post-main](https://github.com/LTstripes/Health-Check/actions/runs/39872257163)
verified 5,622 passed / three declared skips, original ZIP and official validators.
These presentation/summary changes add no schema migration or automatic replay.
#380 wider-window capacity remains blocked and its new controls are not included.
Repeat Owner UAT and a separately bound new candidate/profile/runtime remain
required; the retained 430a11e UAT stays unchanged. Preserve old receipts without
relabeling their code, process-guard provenance or test scope. Documentation gates
and descendants are recorded separately in #479; none authorize profile writes.

Forward v4 sleep metadata preserves independently parsed summary boundaries with
or without phases. It does not recover lost End values from old typed v3 rows.
Scalar validity and a proven duration/boundary check are separate; missing legacy
boundary metadata must be disclosed as unverified, never guessed or silently
reconstructed by raw-body reads. New normalization/offline-reprocess controls are
synthetic engineering evidence, not authority to replay an Owner profile. Historical
frozen packets retain their original rule/version/eligibility and are not rewritten.
The Owner chose to retain scalar-valid old nights in calculations with the
"boundaries not checked" disclosure. No night is removed solely for absent saved
bounds; negatives and proven contradictions remain excluded. Receipts must state
which new/reprocessed data has independent typed bounds and which old rows cannot
prove TST <= session, without claiming complete retrospective validation.

### Candidate and recovery point

1. Freeze one full accepted main SHA/tree. Read live issues/PRs, independent review
   and complete same-attempt exact candidate/main CI under
   [Development](DEVELOPMENT_PROCESS.md#ci-gates). Reconcile target movement; never
   deploy a moving main. Record current installed code/profile/process binding and
   actual read-only schema identity privately.
   Release #479 additionally requires the P1 sleep corrections #483/#484 and the
   approved Garmin corrections #485/#486 to complete their review/exact-CI gates,
   including targeted pipeline, UI and export regressions. Link their new exact
   outcomes; preserve the older rehearsal as older evidence. These quality fixes
   do not authorize raw/history replay, OAuth work or a new profile migration.
2. Clean isolated candidate checkout, locked environment, explicit external profile.
   Preserve matching old code/runtime. Select distinct private backup/UAT/recovery
   targets outside Git/code; verify resolved identities before writes. Do not reuse
   claims or retrospectively adopt a platform checkout into managed lifecycle.
3. With selected profile writers idle, use installed matching code's supported
   backup/verify/restore to a new disposable target. Retain archive/manifest digest,
   code/schema, inventory and verification privately. Supported SQLite online backup
   includes WAL state; a main-DB-only copy is insufficient. Follow
   [backup contents/exclusions](#profile-backup) for protected auth/scheduler recovery;
   do not change or test credentials for release preparation.

### Reproducible clone rehearsal

Bind variables below to approved private paths/full SHA first. $OldCode is installed
matching code; $CandidateCode an isolated accepted checkout; $PreUpgradeBackup a new
archive; $UatProfile a vacant external private target distinct from Stable/code.
Verify native exit codes after each command; stop on failure. Future operator steps:

```powershell
Set-Location -LiteralPath $OldCode
uv run --locked healthcheck backup-profile --data-dir $StableProfile --output $PreUpgradeBackup
if ($LASTEXITCODE -ne 0) { throw 'pre-upgrade backup failed' }
uv run --locked healthcheck verify-backup --backup $PreUpgradeBackup
if ($LASTEXITCODE -ne 0) { throw 'backup verification failed' }
uv run --locked healthcheck restore-profile --backup $PreUpgradeBackup --target-dir $UatProfile
if ($LASTEXITCODE -ne 0) { throw 'clone restore failed' }

Set-Location -LiteralPath $CandidateCode
if ((git rev-parse HEAD).Trim() -cne $CandidateSha) { throw 'candidate SHA mismatch' }
if (git status --porcelain) { throw 'candidate checkout is dirty' }
uv sync --locked
if ($LASTEXITCODE -ne 0) { throw 'locked environment failed' }
$env:HEALTHCHECK_DATA_DIR = $UatProfile
$env:HEALTHCHECK_INGEST_ENABLED = 'false'
uv run --locked healthcheck migrate --data-dir $UatProfile
if ($LASTEXITCODE -ne 0) { throw 'clone migration failed' }
```

For observed Stable startup revision 0016_garmin_daily_summary_receipts, accepted
ancestry is 0016 -> 0017_lab_intake_v1 -> 0018_google_offline_steps.
If actual schema differs, reconcile first. 0017 adds immutable lab entities/heads/
receipts; 0018 recreates four Google stream CHECKs preserving rows/indexes/FKs/
immutable triggers. Do not skip/reorder. See [migration 0017](../src/healthcheck/db/migrations/versions/0017_lab_intake_v1.py)
and [migration 0018](../src/healthcheck/db/migrations/versions/0018_google_offline_steps.py).
Neither migration acquires data, replays sleep history or certifies Google Steps.

Before/after migration use a read-only SQLite connection (mode=ro) on the clone:
exact alembic_version, PRAGMA integrity_check must be ok, PRAGMA foreign_key_check
must return no rows; reconcile pre-existing domain counts/keys and artifact inventory.
Record private results. A file hash/readiness banner does not prove integrity.
Candidate supported backup/verify of migrated clone must pass lab artifact/hash/
reference closure. Restore that archive into another new recovery target and repeat
integrity/schema/closure checks. Preserve failures; synthetic migration CI does not
replace real-profile rehearsal.

Only then start separately approved candidate UI on a free loopback port against
the clone, ingest/provider automation disabled, no scheduler targeting it. Verify
process identity, loaded code, profile/listener; healthz alone is insufficient.
Record the separately agreed final independent targeted recheck against the exact
combined code candidate SHA; task review/CI do not close this additional gate.
Its current receipt/status belongs in release tracker #479.
Run [short Owner UAT](PROJECT_WIKI.md#release-2026-10-22). Retain completed Steps UAT;
no new consent/refresh/provider request/coverage investigation. Do not reuse old
pinned Stable launcher unchanged: its assertions bind old code/schema.

### Rollback and release decision

- Failed migration/integrity/closure or blocking UAT: stop only candidate-owned
  process/writer through approved lifecycle and preserve evidence. Stable stays on
  prior code/profile during rehearsal.
- Restore verified pre-upgrade backup into a new private recovery target with matching
  old code. Verify integrity/schema/artifacts/loaded binding before any approved runtime
  switch. Never run old code on upgraded profile, overwrite Stable ad hoc or force
  downgrade. 0017 refuses to discard staged/accepted lab history; 0018 refuses downgrade
  with immutable Steps evidence.
- Pre-upgrade snapshots omit later writes. Preserve them; obtain explicit reconciliation
  before switching. Never silently discard labs/Context/Weight/collection history.
  Follow backup exclusions; no complete machine/credential recovery is claimed.
- Record final SHA/tree, CI, backup/recovery receipts and UNVERIFIED items in #479.
  After successful rehearsal/UAT obtain separate Stable rollout authorization before
  stop/update/migrate/start. Verify loaded code/profile, schema/integrity and offline
  smoke afterward; retain old recovery point. Tag/release publication is a separate
  decision, not performed by merge or this checklist.

<a id="offsite-backup"></a>

<a id="offsite-backup--protected-offsite-backup-retention-and-clean-recovery"></a>
## Protected offsite backup, retention and clean recovery

Authority: [#148](https://github.com/LTstripes/Health-Check/issues/148),
[Integrator freeze 5962166816](https://github.com/LTstripes/Health-Check/issues/148#issuecomment-5962166816).
This workflow wraps the existing [profile backup primitives](#profile-backup).
It does not contact a cloud service, manage a Scheduler task, or authorize Owner-live work.

<a id="offsite-backup--required-owner-setup"></a>
### Required Owner setup

- Choose an ordinary materialized local NTFS destination outside the profile and checkout.
  A sync client may copy it off-machine; Health-Check sees only filesystem IO.
- Choose explicit local NTFS staging outside profile, checkout and destination.
  It must be non-synced and private to the current Windows user. SYSTEM and local
  administrators are inside the host trust boundary. Broad allow ACLs, null/unsupported
  DACLs and uncertainty are refused. Plaintext residue is possible after a crash;
  an encrypted local staging volume is recommended. No secure erase claim is made.
- Supply an explicit absolute path to an Owner-trusted official `age.exe` v1.3.2.
  No PATH lookup, download/install, plugin or passphrase mode is supported.
  The executable must be a regular single-link non-reparse file outside all workflow roots.
  The version check is not binary provenance/signature verification.
- Supply exactly one native X25519 recipient and one dedicated native X25519 identity file.
  The identity is private, outside profile/checkout/destination/staging and is never archived.
  Store at least one independently tested recovery copy off the laptop, separate from the
  backup destination. Retain old identities while their archives are needed.
- The profile is the trusted local ledger root and must have private access. Do not make
  ACL changes on an existing Owner location without the Owner's explicit approval.

UNC/NAS, mapped/network drives, cloud placeholders/virtual filesystems, FAT/exFAT/ReFS,
reparse points/junctions/symlinks, hardlink/alias ambiguity and uncertain IO are unsupported.
Only one writer machine/profile may manage a destination; sync-replica locks are not distributed locks.
The `--staging-nonsynced` flag is the Owner's explicit attestation, not sync-client detection.

<a id="offsite-backup--publish-and-inspect"></a>
### Publish and inspect

Substitute explicit external paths; never put identity contents in arguments or logs:

```powershell
uv run --locked healthcheck offsite-backup --data-dir $Profile --destination $Destination `
  --staging $Staging --staging-nonsynced --age-executable $AgeExe `
  --recovery-identity $IdentityFile --recipient $Recipient --destination-alias offsite
uv run --locked healthcheck offsite-backup-list --data-dir $Profile `
  --destination $Destination --dry-run
```

The first command creates/verifies ZIP v1 through SQLite Online Backup, encrypts with age,
fully decrypts/authenticates into staging and verifies again. Ciphertext alone is copied to
an exclusive destination-volume `.partial`, flushed/closed, then renamed without overwrite.
The final destination file is reopened, compared with the expected ciphertext SHA-256,
fully decrypted/authenticated and verified through the same primitive. Only then is a
strict JSON receipt published beside it and `offsite-backup-ledger.json` updated atomically
in the source profile. Profile/destination operations are serialized with nonblocking locks.
The transient `.offsite-ledger.lock` is excluded from profile backups; the ledger is included.

The namespace is `hc148-v1-<UTC>-<UUID>.zip.age`; its receipt is that filename plus `.json`.
A final filename/receipt alone is not trusted completion. A crash before completion can
leave an unverified partial, ciphertext or orphan receipt. `publication_uncertain` requires
inspection; do not overwrite/retry the same name. Failure after destination verification
can still mean receipt/ledger completion is missing. No success is inferred from file existence.

<a id="offsite-backup--retention"></a>
### Retention

Keep is fixed at **3**. Trusted ledger append order defines newest points; timestamps, UUIDs
and destination mtimes cannot reorder rotation. Inspect with `offsite-backup-list` before opting into destructive
rotation via the same publication command plus `--rotate`. Rotation only follows a new
successfully verified point; the first missing-ledger run initializes trust without deleting.

Eligibility requires an exact namespace, a strict matching receipt, trusted local creation
record, current expected ciphertext size/hash and a safe single-link regular file identity.
Deletion is bound to the opened Windows handle. The ledger records no destination path or
key material. Missing/invalid/unreadable ledger or inconsistent inventory disables deletion.
Unknown files, partials, orphan/forged receipts, changed/corrupt archives and legacy points
are preserved. The bound is on managed verified points, not all destination contents.
Deletion/ledger failures are separate `retention=partial/failed` outcomes; the new verified
backup remains valid. Inspect `action_required` even when publication succeeded.

<a id="offsite-backup--clean-data-recovery"></a>
### Clean data recovery

Before total-laptop-loss recovery, obtain the archive UUID and expected ciphertext SHA-256
from an independently trusted record preserved outside both laptop and backup destination.
A destination receipt is not sufficient provenance. age authenticates ciphertext integrity,
not author identity, rollback resistance, remote availability or ransomware protection.

```powershell
uv run --locked healthcheck offsite-recover --backup $Ciphertext --target-dir $NewProfile `
  --staging $Staging --staging-nonsynced --age-executable $AgeExe `
  --recovery-identity $IdentityFile --expected-uuid $TrustedUuid `
  --expected-sha256 $TrustedSha256
```

The explicit new external target must not exist; replacement is refused. Its parent must
be private local NTFS. Fingerprint, full decryption/authentication, inner archive validation
and exact runtime migration revision are checked before restore mutation. Older/unknown
revisions require an accepted compatible runtime/recovery decision; no automatic migration
or repair is attempted. Restore reuses the existing primitive with no-overwrite publication.
Then SQLite integrity, migration identity and six capped domain/readiness counts are checked.
A failure after restore reports `target_created` and `restored_readiness_unverified`; it must
not be treated as pre-mutation rejection or automatically retried over the target.

Data recovery is separate from provider access. Machine/user-bound sessions may be unusable;
this command reports reauthorization required conservatively and never opens provider sessions,
decrypts/copies credentials, changes collection policy or performs provider calls.

For the complete Owner-controlled rehearsal:
1. Retrieve ciphertext, independent fingerprint and recovery material from another device/location.
2. Run clean data recovery into a disposable external profile and preserve the original ciphertext.
3. Review restored configuration/absolute paths and collection policy before enabling any operation.
4. Start the accepted loopback UI using explicit `--data-dir`; use the existing `smoke` command
   for supported read paths. The recovery command does not claim that smoke ran.
5. Re-establish Google Web client configuration when needed, then use existing `garmin-auth`
   and `google-auth` under the new Windows user. DPAPI portability is never assumed.
6. Only with explicit Owner approval use bounded accepted `owner-refresh`, preserving intended
   streams/collection policy. See [Owner refresh](#refresh); no implicit backfill.

Status separates created/protected/published/destination_verified, retention and rehearsal.
`offsite_presence` stays `UNVERIFIED` until off-machine retrieval/recovery is actually evidenced.
A local filesystem read-back cannot prove cloud upload or persistence through every power failure.
Lost local ledger records do not authorize adopting destination receipts for deletion.

Automated tests use only synthetic profiles and an explicitly labelled opaque age-process double.
They test orchestration, failure boundaries and native Windows IO, not the cryptographic implementation.
No binary is downloaded or discovered for tests. Official executable interoperability and Owner
protected/off-machine rehearsal remain explicit verification limitations until separately evidenced.

<a id="refresh"></a>

<a id="refresh--selected-profile-refresh-and-scheduler-controls"></a>
## Selected-profile refresh and Scheduler controls

`owner-refresh` is the bounded command for refreshing the established Owner Garmin and Google profile over one shared inclusive local-date window. It reuses provider services, preserves separate checkpoints/semantics, and returns one operational JSON report.

<a id="refresh--accepted-execution-layers"></a>
### Accepted execution layers

Under the established-runtime overlap lock the command runs:

1. Normal Garmin incremental sync.
2. Bounded Garmin Training sync, reusing the Garmin auth/client.
3. Normal Google refresh, using default production streams/list semantics unless optional CLI stream/query overrides select this layer.
4. Fixed sleep-only Google refresh with `query_mode=reconcile` and `dataSourceFamily=google-wearables`, maintaining the R05 exploratory sleep layer.

Normal Google stream selection does not turn off Garmin, Garmin Training or fixed wearables sleep. Overall success requires required substeps to converge as succeeded/empty under their contracts. Preserve partial/failed/reauth and actual freshness honestly.

#395/PR #398 wires the accepted Garmin v1 Steps projector only after successful
persisted routine daily-summary acquisition, preserving exact source/calendarDate,
conflicts, bounds and transaction ownership. This is delivered wiring, not a new
refresh/replay assignment. The separate #410 completed-day display is read-only
and never projects from GET; it does not certify a final Garmin total.

When selected in list mode, high-frequency `heart_rate` is split into civil days, newest first, with individual checkpoint/staging epochs. Each day may use at most two bounded continuation calls after the initial operation; head-page revalidation and 40-page/80-request per-call limits remain. Aggregate counters can exceed one call's limit. A final attempt entry is not a count of all continuation operations. Nonconverged days remain resumable/unknown and stop older-day work.

#206/#207 reduced local promotion/setup work; #212 added narrowly classified bounded transport retries. They did not make refresh a new-records-only operation. The accepted routine horizon is seven days; it deliberately rechecks prior data for corrections. Do not shrink it or skip a selected stream silently to make a run look faster.

<a id="refresh--owner-selected-normal-profile"></a>
### Owner-selected normal profile

Since the Owner decision of 2026-09-29, the local Ops runner defaults **high-frequency Google `heart_rate` to OFF**. Garmin remains the primary high-frequency HR source. Retained normal Google selection:

```text
sleep
hrv
daily_hrv
daily_resting_hr
spo2
daily_spo2
respiratory_rate_sleep
daily_respiratory_rate
```

The runner supplies these via repeated `--stream` arguments. It adds `heart_rate` only when its local enable flag exists. This does not remove historical Google HR records, disable HRV/resting-HR summaries, change provider/query/correction semantics or disable fixed wearables-sleep reconciliation.

**The bare repository CLI default is unchanged and includes high-frequency HR.** Use the Scheduler task or Ops wrapper for this selected profile. A direct command without explicit stream selection bypasses the local flag.

The historical Google HR gap is intentionally not a backfill target while disabled. Re-enabling affects future selected windows, not all missing history; review dates/coverage before a separate bounded historical operation. Disabled/unrequested evidence must not be described as complete or provider-empty.

<a id="refresh--local-assignment-and-deployment-state"></a>
### Local assignment and deployment state

| Role | Owner-local location |
| --- | --- |
| Accepted-code operation checkout | `D:\HealthCheck\main` |
| Durable private data | `D:\HealthCheck\stable` |
| Operational wrapper | `D:\HealthCheck\ops\owner-refresh-scheduled.ps1` |
| Enable Google sample HR | `D:\HealthCheck\ops\google-hr.enabled` |
| Private operational logs | `D:\HealthCheck\stable\logs\owner-refresh-*.log` |
| Task name | `Health-Check owner refresh` |

These are operational roles, not Worker development locations. The concrete
path-role table is owned by [machine layout](#machine-layout). Actual task action
and loaded-code/profile binding must be read back before an authorized operation;
do not infer them from a merge or an old rollout. Dated installed/accepted/UAT
status is maintained once in [Wiki](PROJECT_WIKI.md#current-canonical-state).

Before an explicit safe code update verify accepted target SHA, clean local state and idle relevant Owner processes, including refresh and application processes using that checkout. Do not switch/pull mid-run. This closeout does not itself modify the task, wrapper, checkout or Stable data.

<a id="refresh--manual-controls-using-the-existing-task"></a>
### Manual controls using the existing task

Run under the same Windows account that established protected sessions:

```powershell
Start-ScheduledTask -TaskName 'Health-Check owner refresh'
Get-ScheduledTask -TaskName 'Health-Check owner refresh' | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName 'Health-Check owner refresh' |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
```

HR toggle, applied at the next runner start:

```powershell
# ON only after an explicit Owner choice
New-Item -ItemType File -Path 'D:\HealthCheck\ops\google-hr.enabled' -Force | Out-Null
# OFF
Remove-Item -LiteralPath 'D:\HealthCheck\ops\google-hr.enabled' -ErrorAction SilentlyContinue
```

Disable/enable future task execution:

```powershell
Disable-ScheduledTask -TaskName 'Health-Check owner refresh'
Enable-ScheduledTask -TaskName 'Health-Check owner refresh'
```

Real in-flight `Stop-ScheduledTask` was not validated by the operational check. Do not present it as graceful cancellation or exercise it for a checkbox. Interruption requires checking final task/log state and supported recovery before further mutation; never kill all Python processes or edit SQLite directly.

Watching a log with `Get-Content -Wait` is separate from running refresh. Ending that viewer is not a tested cancellation mechanism for the provider process.

<a id="refresh--direct-cli--explicit-profile-selection"></a>
### Direct CLI / explicit profile selection

From an accepted checkout:

```powershell
uv run --locked python -m healthcheck.cli owner-refresh `
  --data-dir $OwnerDataDir `
  --trailing-window-days 7
```

This uses the full default normal Google selection, including HR. To match HR-OFF, supply all eight retained streams or use the existing Ops task/wrapper.

`--date YYYY-MM-DD` fixes the inclusive end date; otherwise local date is used. Windows are bounded to 1–14 days. The command requires an established external profile/config/migrated database and fails closed rather than creating a profile after a mistyped path. Overlapping supported operations on the same profile are rejected by the external-runtime lock. Routine refresh does not imply historical backfill, reprocess or reauthentication.

<a id="refresh--scheduler-configuration-and-accepted-automatic-proof"></a>
### Scheduler configuration and accepted automatic proof

Owner/Codex reported configuration:

- Daily 10:30 Windows local time, plus Owner logon.
- Interactive Owner account, limited privileges.
- `StartWhenAvailable=True`, `MultipleInstances=IgnoreNew`.
- Battery start allowed; switching to battery does not itself stop the task.
- `WakeToRun=False` in the observed configuration.
- Existing wrapper/HR flag retained; protected secrets are not task arguments.

Battery permissions do not prove execution through sleep. A closed lid, sleep/offline interval, full shutdown, logon and unlock are different conditions. LastRunTime alone is not active CPU/wall execution duration; a small log without progress output alone is not proof of a hang. IgnoreNew prevents overlap, not sequential additional logon runs or once-per-day duplicates.

<a id="refresh--limits-of-operational-proof"></a>
#### Limits of operational proof

The accepted #214 automatic/logon proof and earlier failed/manual attempts remain
in the [dated closeout](archive/closeouts/OWNER_REFRESH_CLOSEOUT_2026-10-01.md).
One automatic success is not proof of graceful cancellation, sleep/resume continuity,
multi-day reliability or installed newer code. Keep private logs local; public
engineering reports contain sanitized technical summaries, never whole private
logs, raw values, tokens or databases. Re-enabling disabled Google HR does not
authorize a broad historical backfill. No provider work is performed by maintaining
this documentation.

<a id="screenshot-import"></a>

<a id="screenshot-import--weight-screenshot-handoff-commands-review-and-integration"></a>
## Weight screenshot handoff, commands, review and integration

<a id="screenshot-import--work-handoff"></a>
### Work handoff

The Work-side integration passes the single uploaded PNG or JPEG attachment as a local file path to one bounded CLI call:

```powershell
uv run --locked healthcheck owner-weight-screenshot-import `
  --data-dir "D:\HealthCheck\stable" `
  --image "<path to this uploaded attachment>"
```

When Work/Codex can inspect the attachment itself, it may instead provide one temporary
strict `r01-photo-v1` extraction object:

```powershell
uv run --locked healthcheck owner-weight-screenshot-import `
  --data-dir "D:\HealthCheck\stable" `
  --image "<path to this uploaded attachment>" `
  --extraction-json "<temporary JSON outside the repository>"
```

When the Owner explicitly states the source date in the same request, Work may add
`--owner-attested-date "YYYY-MM-DD"` together with `--extraction-json`. Never supply
it from memory, prior chat, filename, EXIF, clock, or defaults, and never without the
sidecar. An attested date is strictly date-only: the sidecar must carry no source
timestamp, timezone, UTC offset, or non-date precision, otherwise the request is
rejected before any write. Provider vision routes never accept attestation.

This sidecar is bounded to 512 KiB, parsed and profile-checked before the R01 photo service
writes evidence, and uses the fixed `healthcheck-owner-assisted-structured-extraction` v1
identity with no invented model identity. It must contain the same strict structured payload
accepted from the configured vision adapter; there is no second schema or normalization path.
The caller removes the temporary JSON after the command and never stores or publishes it.

The established profile must already exist. Configure the existing real photo extractor through the normal `HEALTHCHECK_PHOTO_VISION_BASE_URL`, `HEALTHCHECK_PHOTO_VISION_MODEL` and `HEALTHCHECK_PHOTO_VISION_API_KEY` environment settings. The API key is never passed as a CLI argument. The command refuses a missing/unready profile, reads at most the existing 10 MiB photo limit, accepts PNG/JPEG, and stores evidence in the profile's content-addressed R01 photo store. It does not print the supplied path, filename, extracted values, dates, provider response, or exception text.

The external vision configuration is not required or called when `--extraction-json` is
present. Without that option, the configured-provider behavior is unchanged. Malformed,
unreadable or oversized sidecars fail with a fixed safe reason before photo persistence;
Owner-profile conflicts fail closed before confirmation.

Work should pass arguments as separate process arguments, make one invocation for one attachment and use only the returned status. It must not scan a folder, retry a review result, confirm through SQL, or require the openScale webhook. The screenshot attachment itself is not rewritten.


<a id="screenshot-result"></a>

<a id="screenshot-result--screenshot-result-and-integration-gates"></a>
## Screenshot result and integration gates

<a id="screenshot-result--work-result-contract"></a>
### Work result contract

The command writes one privacy-safe JSON object to stdout:

| Status | Exit code | Work action |
| --- | ---: | --- |
| `IMPORTED` | 0 | Report that the screenshot import completed; do not repeat the import. |
| `DUPLICATE` | 0 | Report that the same evidence was already handled; no new measurement was written. |
| `NEEDS_REVIEW` | 3 | Stop automation and direct the Owner to the existing Health-Check import review; a staged correction appears in the original import batch. |
| `FAILED` | 1 | Stop automation and report the safe reason code; do not echo the file path or retry indefinitely. |

The JSON includes only status, a fixed reason code and structural candidate/measurement counts, plus privacy flags. It never includes health values, timestamps, content hashes, artifact/candidate IDs, filenames or provider text.

<a id="screenshot-result--integration-gate"></a>
### Integration gate

The synthetic worker gate exercises the CLI, existing R01 photo contracts, provenance and replay behavior:

```powershell
uv run --locked ruff check src/healthcheck/owner_weight_screenshot_import.py src/healthcheck/cli.py tests/test_owner_weight_screenshot_import.py tests/test_metadata_origins_240.py
uv run --locked pytest -q -p no:cacheprovider tests/test_owner_weight_screenshot_import.py tests/test_photo_import.py tests/test_photo_vision.py tests/test_metadata_origins_240.py
uv run --locked python scripts/ci_test_lanes.py validate-manifest
```

The new test file is assigned to the existing `app-ingest` CI lane; it does not create a new test lane.

Before enabling the Work handoff against Stable, the Owner/Integrator gate remains required and must be performed with a recovery point and a private Xiaomi Home screenshot on the actual Work-to-local-CLI path:

1. Upload one screenshot in ChatGPT Work and verify Work invokes this CLI against `D:\HealthCheck\stable` with that one attachment.
2. For a clear screenshot, verify through the normal Health-Check read path that one photo evidence/candidate set is retained and exactly one source measurement session is confirmed with Xiaomi Home, Xiaomi S400, `photo_import`, original photo hash, R01 algorithm identities and evidenced temporal precision.
3. Replay the identical attachment. It must return `DUPLICATE` and leave the measurement/session/canonical counts unchanged.
4. Exercise one ambiguous screenshot; it must return `NEEDS_REVIEW` and create no semantic measurement or canonical change.
5. Verify the pre-existing Stable history remains intact. Keep the private screenshot, values, identifiers and runtime evidence out of Git and task logs.

Until this live gate is completed, ChatGPT Work-to-Stable is `UNVERIFIED`; synthetic tests do not claim Owner UAT or Integrator acceptance.

<a id="screenshot-result--historical-153-context"></a>
### Historical #153 context

#153 (openScale-sync webhook numeric `userId` compatibility) was closed by the Owner as not planned: screenshot ingestion is the accepted operational Weight path. The historical receiver note (non-empty string `userId`) is retained only as deferred context. This task does not change that contract or implement a webhook fix. The screenshot command is an independent Owner path and must not depend on webhook setup or availability.
The complete auto-confirm, metadata-origin, correction and provenance contract is in [Architecture](ARCHITECTURE.md#photo-provenance). UI rendering success cannot replace the screenshot result/integration gates.


<a id="context-operations"></a>

<a id="context-operations--context-commands-and-durable-saveread-back"></a>
## Context commands and durable save/read-back

<a id="context-operations--commands"></a>
### Commands

The profile must already be migrated to Alembic head
`0013_context_capture_v0`.

```powershell
uv run --locked healthcheck context-add `
  --data-dir D:\path\to\profile `
  --date 2026-09-22 `
  --text "Synthetic note" `
  --tag tennis `
  --tag fatigue

uv run --locked healthcheck context-list `
  --data-dir D:\path\to\profile `
  --from 2026-09-01 `
  --to 2026-09-30 `
  --limit 50

uv run --locked healthcheck context-revise `
  --data-dir D:\path\to\profile `
  --event-id <event-uuid> `
  --text "Synthetic corrected note" `
  --operation-id <caller-retry-key>
```

List filtering uses inclusive owner-local calendar dates and interval overlap.
Ordering is deterministic and most-recent-first. The default limit is 50 and
the hard maximum is **200**. Add/revise success output omits the note text;
`context-list` deliberately returns context notes but never reads or emits
unrelated provider or health evidence. Validation/storage errors do not echo
the submitted note.


<a id="context-evidence"></a>

<a id="context-evidence--context-evidence-and-verification"></a>
## Context evidence and verification

<a id="context-evidence--chat-evidence--standalone-stage-a-implemented-transport-later"></a>
### Chat evidence — standalone Stage A implemented, transport later

The #294 portal adapter above is implemented. [#341 Stage A](https://github.com/LTstripes/Health-Check/issues/341)
now supplies a separate bounded read-only standalone Weight/Garmin-scalars/
current-Context evidence envelope without changing Context history, original
text or Period Brief hashes. Its command, privacy/output-path restrictions and
coverage limits live in [Health Chat Evidence](ARCHITECTURE.md#evidence-period).
Historical first private manual sharing was confirmed by the accepted #341 decision; later source services and the #455 local download form are delivered. Authenticated direct ChatGPT connection remains unverified; see Wiki for current evidence boundaries.

The [#342 offline clone diagnosis](https://github.com/LTstripes/Health-Check/issues/342#issuecomment-6087155625)
is accepted as historical source classification, not a fresh provider recovery.
Source absence cannot be inferred from comments or repaired by a model.

Routine comments must be saved to the explicitly selected **durable Owner profile**
after a safe rollout. A note entered in a disposable UAT clone is not automatically
part of Stable and must not be silently discarded or claimed as a production note.
Implementation uses synthetic data only. Private exported notes are evidence for
Owner-selected discussion, never instructions for model tool execution or content
for public GitHub/CI logs.

<a id="analysis-export"></a>

<a id="analysis-export--saved-evidence-export-and-ui-workflow"></a>
## Saved evidence export and UI workflow


Use an explicit existing external profile and profile classification; read commands
do not prepare runtime, migrate, refresh providers or prove current Stable identity.
Choose source IDs using the matching domain discovery contract. The following full
examples preserve source-specific CLI selection and the UI disclosure/guard rules.
Envelope definitions and hashes are canonical in Architecture.


<a id="combined-export"></a>

<a id="combined-export--combined-export-desktop-analysis-ui"></a>
## Combined export desktop analysis UI

<a id="combined-export--desktop-ui-local-analysis-downloads-451"></a>
### Desktop UI: local analysis downloads (#451)

Bare `/` opens Overview (`/brief`); Weight has the canonical `/weight` route.
Existing root links carrying query parameters retain their Weight destination
and unchanged query string. Explicit section links and APIs keep their routes.

**Данные → Скачать данные** (`/imports#analysis-export`) owns the download form;
Overview links to it without embedding export controls. Select 7 or 30 inclusive
calendar dates and an end date, then choose **Скачать**. A text download begins
after both existing serializers finish; JSON and the same text remain available
under **Файл, JSON и подробности данных**. The visible label states that current
comments are included. **Источники и состав файла** discloses the supported
manifest, source selectors and limits, and opens when source selection is needed.
The one
Garmin selection is explicitly used for Activity, Sleep, Stress, Body Battery,
weekly HRV, RHR and the selected Steps view; it never falls back to another Garmin source.
Weight and current Context are included. Google Sleep and RHR use their existing
metric-specific eligibility selection, retaining conflicts/incomplete outcomes.
Google daily HRV uses the exact source shown in its separate selector, or is
omitted when **Не включать** is selected. A unique inventory source is preselected
visibly in the disclosed selector; competing sources require a choice. A sole
inventory identity is only a selector default, never proof of metric eligibility
or completeness; existing readers retain authority. The UI does not pool providers.

`GET /api/analysis-export/sources` reads only bounded saved source identities,
with a fail-closed 32-source ceiling per provider table. It does not query provider
accounts. `POST /api/analysis-export` accepts dates and source IDs, never a profile
path. It uses the running UI's configured local runtime, explicitly classifies it
as private durable-runtime evidence, and calls the existing combined reader once
with compact projection. This is a caller classification, not verification of a
Stable identity or of the underlying data's origin. Local synthetic checks use
only synthetic profiles; the UI conservatively labels their exports private too.

Both unchanged serializers must finish under their existing independent 2 MiB
limits before either file becomes available. The two downloads use the same
frozen packet, period and envelope identity; downloading again does not read the
database again. Responses are `Cache-Control: no-store`; the server creates no
export files or retained packet cache. Browser Blob URLs live in the current tab,
are revoked on parameter changes, regeneration or page exit, and are not uploaded.
User-downloaded files remain in the browser's ordinary download destination.

The primary UI keeps short missing/invalid/conflict/search outcomes and partial
period qualifiers visible; routine methodology, provenance and repeated source
freshness live in accessible info/details. Saved history is not hidden by an
overdue refresh. Details retain reader states/counts and warnings without
interpreting health values. Context keeps the existing 50-row
page: `has_more`/`truncated` is disclosed, not presented as a complete archive.
All other existing reader, SQL/time and output limits remain. Oversize or failed
reads/serialization produce an error and no downloadable prefix. Changing controls
invalidates prior downloads and ignores/aborts stale in-flight responses. A failed
request can be retried; unavailable inventory has its own retry control.

This is a potentially megabyte-sized evidence export, not a short summary or a
clipboard promise. No clipboard action, external AI/API call, automatic transfer,
provider refresh, ingestion, MCP change, Stable deployment or schedule is added.
Observed Steps retain unknown finality/coverage; Body Battery remains saved-sample
maxima, and Garmin weekly versus Google daily HRV remain different series. Existing
missing/null/zero, date precision, provenance and causal limits are unchanged.







### Weekly preview and remaining delivery gate (#488)

The code-only preview is available through the existing Overview when a trusted
caller explicitly supplies `WeeklyDigestConfig` and `profile_kind` to
`create_ui_app`; it is disabled by default. The same source configuration can be
passed as `MCPConfig.weekly_digest`, exposing only the Sunday `week_end` argument.
Use external synthetic profiles for tests. The accepted semantics and frozen
packet contract are in [Architecture](ARCHITECTURE.md#weekly-digest-preview-488).
Neither factory call installs or starts a service. Existing CLI/runtime settings
are unchanged; choosing real source IDs or enabling access remains separate.

The agreed target is Sunday 20:00 Europe/Moscow. **No schedule or automatic chat
delivery is active.** Before enabling it, verify the authenticated end-to-end
bounded read and existing personal-chat destination, trusted source configuration,
profile availability, privacy, and an explicit offline/late-delivery policy. An
offline laptop cannot provide fresh evidence: report unavailability rather than
inventing values. A late read must display actual as-of, never pretend to restore
the earlier Sunday snapshot. Future transport must freeze the report before
sending, reuse that exact packet/hash on retry, deduplicate delivery, and require
an explicit revision for new evidence. Those transport behaviors are still
unimplemented and require their own verification; the envelope is only their
connection contract. No new credentials, provider calls or Stable changes follow
from this preview.


<a id="combined-cli"></a>

<a id="combined-cli--combined-standalone-cli"></a>
## Combined standalone CLI

<a id="combined-cli--standalone-cli"></a>
### Standalone CLI

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-08 --days 7 \
  --activity-garmin-source-id <activity-id> \
  --sleep-garmin-source-id <sleep-id> --sleep-google-source-id <google-id> \
  --evaluation-local-date 2099-01-08 \
  --output-dir <new-external-directory>
```

Either Sleep ID option may be omitted, but not both. `--context-limit` is
optional; `--no-include-context` skips Context entirely. The evaluation instant
is captured in UTC at invocation and the local evaluation date is explicit,
never inferred from the host zone. The command writes `evidence.json` and
`evidence.txt` from the same frozen packet only after both serializations pass.

`--output-dir PATH` and `--stdout json|text` are required and mutually exclusive.
`--stdout` emits only the selected existing serializer result for the one frozen
packet and no status line: `json` is `encode_combined_evidence`, `text` is
`render_combined_evidence`. The complete result is validated and constructed
before any byte reaches stdout, so a read, validation or serialization failure
leaves stdout empty with a bounded code on stderr and a nonzero exit. A malformed
stdout request — missing, invalid or conflicting options, including `--stdout`
combined with `--output-dir` in either order — likewise writes no payload and
prints one bounded code, never the arbitrary supplied values, and reads no data.
Stdout mode never creates the output directory and writes no `evidence.json`/`evidence.txt`.
Stdout receives the exact UTF-8 bytes of the serializer result even when the
active console encoding cannot represent some characters, so the packet is never
re-escaped into invalid JSON, substituted or truncated. The user redirects or
pipes stdout explicitly. This command runs in the local executor: it is not a
live assistant connection, no upload occurs, and captured/redirected stdout can
contain private owner context, so any resulting file is private Owner data.

The output directory must be new and outside the profile and any Git checkout
(including `.git` worktree files). Repeat `--agent-workspace-root` to also
exclude development roots without Git markers. These checks happen before
reading data. No files are overwritten. A filesystem failure during writing can
leave a partial new output directory; the command reports failure, never export
success. Read/validation/serialization failure creates no output directory.
Console errors contain bounded codes, without health text or profile paths.

No implicit/default profile, missing DB creation, runtime preparation, migration,
environment/config scan, raw provider-body read, provider call, OAuth/MCP setup,
Stable operation or database write is part of this command. Missing/unmigrated
databases fail without repair. Automated checks use external synthetic profiles
only. Independent data/privacy review and exact-candidate CI remain separate
from Owner export/UAT and connection verification.

Google Sleep may be requested without a technical ID with
`CombinedEvidenceRequest.sleep_google_auto_select=True` or CLI
`--sleep-google-auto-select`. The exact Sleep override still takes precedence.
This delegates to the same [Sleep selection contract](ARCHITECTURE.md#metric-source-selection);
Activity selection and omitted-provider behavior are unchanged. A blocked Google
choice remains a labelled section with selection evidence and `source_range=null`,
and is preserved in both JSON and text.




<a id="export-completed-steps-v5"></a>

### Explicit completed Steps v5

This complete example uses an explicitly existing profile and exact sources. Select the matching version only; omitted optional flags retain earlier defaults. The profile/output/privacy guards in [analysis export](#analysis-export) and [Architecture](ARCHITECTURE.md#evidence-combined) remain in force. These `text` blocks show CLI argument continuations, not a PowerShell script to execute unchanged.

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2025-12-31 --days 7 --activity-garmin-source-id <activity-id> \
  --sleep-garmin-source-id <sleep-id> \
  --steps-garmin-source-id <steps-id> --completed-day-steps \
  --evaluation-local-date 2025-12-31 --projection compact --stdout json
```

The Sleep selector is mandatory under the existing combined request contract; the original v5 documentation example omitted it. Adding it repairs that example without changing the CLI default or Steps semantics.

<a id="export-observed-steps-weight-v4"></a>

### Observed Steps and Weight v4

This complete example uses an explicitly existing profile and exact sources. Select the matching version only; omitted optional flags retain earlier defaults. The profile/output/privacy guards in [analysis export](#analysis-export) and [Architecture](ARCHITECTURE.md#evidence-combined) remain in force. These `text` blocks show CLI argument continuations, not a PowerShell script to execute unchanged.

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-31 --days 30 \
  --activity-garmin-source-id <activity-id> --sleep-garmin-source-id <sleep-id> \
  --steps-garmin-source-id <observed-steps-id> --include-weight \
  --evaluation-local-date 2099-01-31 --projection compact --stdout json
```

<a id="export-vitals-v3"></a>

### HRV and resting heart rate v3

This complete example uses an explicitly existing profile and exact sources. Select the matching version only; omitted optional flags retain earlier defaults. The profile/output/privacy guards in [analysis export](#analysis-export) and [Architecture](ARCHITECTURE.md#evidence-combined) remain in force. These `text` blocks show CLI argument continuations, not a PowerShell script to execute unchanged.

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-31 --days 30 \
  --activity-garmin-source-id <activity-id> --sleep-garmin-source-id <sleep-id> \
  --hrv-garmin-source-id <weekly-hrv-id> --hrv-google-source-id <daily-hrv-id> \
  --rhr-garmin-source-id <rhr-id> --rhr-google-auto-select \
  --evaluation-local-date 2099-01-31 --projection compact --stdout json
```

<a id="export-stress-body-battery-v2"></a>

### Stress and Body Battery v2

This complete example uses an explicitly existing profile and exact sources. Select the matching version only; omitted optional flags retain earlier defaults. The profile/output/privacy guards in [analysis export](#analysis-export) and [Architecture](ARCHITECTURE.md#evidence-combined) remain in force. These `text` blocks show CLI argument continuations, not a PowerShell script to execute unchanged.

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-31 --days 30 \
  --activity-garmin-source-id <activity-id> --sleep-garmin-source-id <sleep-id> \
  --stress-garmin-source-id <stress-id> \
  --body-battery-garmin-source-id <battery-id> \
  --evaluation-local-date 2099-01-31 --projection compact --stdout json
```

<a id="export-compact-v1"></a>

### Compact projection with earlier defaults

This complete example uses an explicitly existing profile and exact sources. Select the matching version only; omitted optional flags retain earlier defaults. The profile/output/privacy guards in [analysis export](#analysis-export) and [Architecture](ARCHITECTURE.md#evidence-combined) remain in force. These `text` blocks show CLI argument continuations, not a PowerShell script to execute unchanged.

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-31 --days 30 \
  --activity-garmin-source-id <activity-id> \
  --sleep-garmin-source-id <sleep-id> --sleep-google-source-id <google-id> \
  --evaluation-local-date 2099-01-31 --projection compact --stdout json
```

Current compact JSON declares `projection.sleep_evidence_schema` as
`compact-sleep-evidence-v3`. Resolve each endpoint-array index through the same
saved session's `session_interval_sets`; after overlaying common and cell evidence,
resolve its `quality_inputs_index` through that source session's
`quality_input_sets`, following
[Architecture reconstruction](ARCHITECTURE.md#evidence-combined--opt-in-compact-projection).
Earlier v2 packets retain their endpoint registry and inline quality inputs;
packets without the discriminator retain inline arrays. Do not rewrite a saved
packet or infer a successful check from absent historical validation metadata.
Selected facts and readable text retain the bounded boundary-validation note;
full summary provenance remains in
the matching JSON. Existing byte/profile/privacy guards still apply.

<a id="health-chat-evidence-commands"></a>

<a id="health-chat-evidence-commands--health-chat-evidence-command-examples"></a>
## Health Chat Evidence command examples

```powershell
uv run --locked python -m healthcheck.export_chat_evidence `
  --profile D:\path\to\selected-profile `
  --profile-kind synthetic `
  --from 2099-05-01 --to 2099-05-03 `
  --domain weight --domain garmin --domain context `
  --metric stress_daily_average --metric sleep_duration_seconds `
  --garmin-source-id <persisted-source-id> `
  --weight-cadence-days 7 `
  --limit 50 --output-dir D:\path\to\new-export-directory
```


<a id="sleep-chat-evidence-commands"></a>

<a id="sleep-chat-evidence-commands--sleep-chat-evidence-command-examples"></a>
## Sleep Chat Evidence command examples




<a id="activity-chat-evidence-commands"></a>

<a id="activity-chat-evidence-commands--activity-chat-evidence-command-examples"></a>
## Activity Chat Evidence command examples




<a id="mcp-service"></a>

<a id="mcp-service--mcp-startup-synthetic-verification-and-connection-procedure"></a>
## MCP startup, synthetic verification and connection procedure

<a id="mcp-service--reproducible-synthetic-checks"></a>
### Reproducible synthetic checks

From the isolated candidate checkout, with the locked development environment:

```powershell
uv run --locked python scripts/check_chat_evidence_mcp.py
```

This creates a fresh external temporary **synthetic** profile, seeds one fake
Weight observation and one synthetic Context note, tests HTTP initialization,
tool discovery/call, matching representations and unchanged DB/WAL/file fingerprints,
then cleans up its own fixture. Synthetic fixture preparation is confined to the
check script; the server has no migration/preparation path. No network listener,
public tunnel, provider call, credential or key creation occurs.
SQLite's WAL shared-memory (`healthcheck.db-shm`) reader coordination is exempt
from byte/mtime equality, as in the accepted WAL-aware reader contract; the
database, WAL and unrelated files remain covered by the fingerprint check.

Focused regressions (set the two paths to fresh external synthetic children):

```powershell
$env:HEALTHCHECK_DATA_DIR = "$env:TEMP\hc341-evidence-runtime-synthetic"
uv run --locked pytest tests/test_chat_evidence_mcp.py tests/test_chat_evidence.py --basetemp "$env:TEMP\hc341-evidence-pytest-synthetic"
```

Use fresh disposable temp paths; pytest's `--basetemp` can remove an existing
directory. Never substitute an Owner/private profile or output location.

For optional local MCP Inspector testing, retain only a synthetic fixture:

```powershell
uv run --locked python scripts/check_chat_evidence_mcp.py --keep-profile
uv run --locked python -m healthcheck.chat_evidence_mcp --profile <printed-synthetic-profile> --profile-kind synthetic --timezone UTC --origin http://localhost:6274
npx @modelcontextprotocol/inspector@latest
```

Select Streamable HTTP and `http://127.0.0.1:8787/mcp`. Use the actual Inspector
browser origin if its port differs. Initialize, list tools and call with:

```json
{"start":"2099-05-01","end":"2099-05-03","domains":["weight","context"]}
```

Inspector is an optional manual interoperability check, not evidence already
performed by the automated smoke. Stop the foreground server with Ctrl+C.

<a id="mcp-service--prepare-personal-chatgpt-connection-over-https"></a>
### Prepare personal ChatGPT connection over HTTPS

Official documentation checked 2026-10-09:
[personal plugin quickstart](https://developers.openai.com/plugins/quickstart),
[connection flow](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[authentication](https://developers.openai.com/plugins/build/auth),
[Streamable HTTP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
Personal custom MCP creation is subject to actual account/workspace permissions;
neither this code nor documentation proves that this account has that option.
ChatGPT does not dial the laptop's loopback address directly.

For a first **synthetic-only** connection, an Owner-authorized HTTPS deployment or
forwarder can route **only `/mcp`** to `http://127.0.0.1:8787/mcp`, preserving POST,
Accept and MCP-Protocol-Version. Set upstream Host to `127.0.0.1:8787`; preserve
Origin and explicitly allow the necessary exact origin. Do not forward the whole
Health-Check app. Use `https://<owner-selected-host>/mcp` as the Server URL and
No authentication only while the fixed profile is synthetic. This task starts
no HTTPS service, public tunnel or background service and supplies no credentials.

Owner profiles require the complete [Architecture gateway/auth contract](ARCHITECTURE.md#mcp-boundary), including startup secret, every-request OAuth validation, narrow forwarding and revocation. If access setup is absent, Owner-data HTTPS is BLOCKED; retain manual export.

Once the chosen HTTPS endpoint and access gate have separately passed Inspector:

1. In ChatGPT Plugins select (+) → Add custom MCP server, if permitted.
2. Name it Health-Check evidence; set the HTTPS Server URL including `/mcp`.
   Choose No authentication for synthetic-only, or the gateway's OAuth flow for
   Owner data. Review consent and select Create as a plugin. No plugin manifest,
   marketplace submission or custom UI is required for this personal MCP flow.
3. Confirm discovery lists exactly `get_period_evidence` with read-only annotations.
   Install/select the plugin in a new supported chat using `@`.
4. Request the synthetic period above; verify an actual tool invocation and matching
   evidence. Test invalid domain/range, unavailable profile and access denial.
5. Owner data needs separate authorization and one explicit bounded private query.
   Confirm the expected profile assertion/range and no values in infrastructure logs.
   Stop forwarding/server, disconnect the plugin and revoke the gateway token;
   a subsequent call must fail. Revoke/replace the internal credential and restart
   the facade to invalidate that credential too; no persistent service is installed.

Local synthetic PASS, exact-candidate CI, independent privacy/transport review,
account custom-plugin entitlement, HTTPS/OAuth interoperability and connected
Owner UAT are separate evidence. Until the last steps are actually performed,
direct access is **UNVERIFIED**, never CONNECTED.
Canonical tool/transport and gateway auth requirements are in [Architecture](ARCHITECTURE.md#mcp-boundary). A local synthetic result does not establish a real ChatGPT connection; private connection/auth/revocation remains separately authorized.


<a id="garmin-auth"></a>

<a id="garmin-auth--garmin-owner-assisted-auth-and-bounded-probe"></a>
## Garmin owner-assisted auth and bounded probe

<a id="garmin-auth--owner-live-step"></a>
### OWNER LIVE STEP

Run these commands from the checked-out task branch, with `uv` available. The
default path below is outside the checkout and is the only place where the
protected Garmin session envelope is created. On Windows it is bound to the
current user's DPAPI key and owner SID; if user-scoped protection is
unavailable, auth fails closed.

```powershell
$ownerData = Join-Path $env:LOCALAPPDATA "Health-Check"
uv run --locked healthcheck garmin-auth --data-dir $ownerData
```

The command prompts for the Garmin email and password without command-line
arguments and without echoing input. If Garmin requests MFA, it prompts for
the MFA code without echoing or storing it as report output. The provider
receives an inline token snapshot; no plaintext temporary token file is
created. The command emits only a fixed-vocabulary auth result. A malformed
or poisoned local envelope returns `reauth_required` and the same command is
the deterministic owner recovery path. Provider outage remains `failed`. If
the cached session is expired or unusable, rerun the same command; to
explicitly replace a usable cached session, use:

```powershell
uv run --locked healthcheck garmin-auth --data-dir $ownerData --force-reauth
```

After authentication, choose one recent date (or two adjacent recent dates)
that the owner wants to inspect and run the separate probe. The example uses
today; replace `$probeDate` with another recent `yyyy-MM-dd` value if needed:

```powershell
$probeDate = (Get-Date).ToString("yyyy-MM-dd")
uv run --locked healthcheck garmin-capabilities --data-dir $ownerData --date $probeDate
```

For two adjacent dates:

```powershell
$probeDate = (Get-Date).ToString("yyyy-MM-dd")
$previousProbeDate = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
uv run --locked healthcheck garmin-capabilities --data-dir $ownerData --date $previousProbeDate --date $probeDate
```

The probe makes one fixed activity-search request with `start=0` and
`limit=1`, rather than invoking pinned `get_activities_by_date` pagination.
At most one selected activity receives a summary request and
`get_activity_details(maxchart=1, maxpoly=0)`. Pinned-provider retries are
disabled and the hard probe cap is 27 provider requests. No GPS/polyline route
request or ORIGINAL FIT download is made. Recovery Time is therefore reported
as `not_evaluated` until a correct bounded FIT parser exists. If any call
reports reauthentication, remaining calls are aborted and rows are marked
`not_run` with `not_run_reason=reauth_required`. It does not perform broad
backfill and does not write Health-Check database tables. Its stdout is a
machine-readable sanitized summary. Save or copy only that summary, never
provider logs or raw responses.

The summary reports, per capability:

- whether the method is callable and whether its request succeeded;
- response shape, bounded counts, safe field paths, and present/empty/null or
  missing state;
- unsupported/404-like, expired-session, shape-drift, and other fixed error
  classes;
- coarse target-device/other-device/mixed/unattributed/unknown evidence;
- only allowlisted metric leaf/path evidence; a non-empty root object or
  method presence is not evidence;
- the static R00 status next to the live observation, without changing it.

It never reports health values, activity/profile/device IDs, routes,
coordinates, precise health timestamps, email, device serials, cookies,
tokens, or raw payloads. `target_device_evidence` is false unless the response
has a present value and explicit target-device evidence. Method presence alone
is not capability evidence.

<a id="garmin-auth--optional-sanitized-shape-export"></a>
### Optional sanitized shape export

The probe does not save raw responses. If the owner separately has a raw JSON
response and later needs to share its structure, keep both files outside the
checkout and run:

```powershell
$rawPath = Join-Path $ownerData "owner-only\raw-response.json"
$sanitizedPath = Join-Path $ownerData "owner-only\sanitized-shape.json"
uv run --locked healthcheck garmin-redact --input $rawPath --output $sanitizedPath
```

The helper rejects checkout-local or symlinked input/output paths, omits
unknown/provider-added keys are aggregated as redacted counts, and writes only
a value-free bounded shape. Do not copy the raw input, tokenstore, logs, screenshots, or the
owner-only directory into Git or an issue comment. Share only the sanitized
summary/shape if explicitly requested.


<a id="garmin-daily-summary-reacquisition"></a>
### Bounded repair of unproven daily-summary acquisitions

Use this separately authorized mode when historical coverage exists but the
completed-day reader lacks acquisition proof. Run only an accepted compatible
installation against the explicitly assigned existing profile. First confirm the
profile writer is idle and prepare/verify the normal rollback backup. Select the
exact stored Garmin source from the existing read-only source selection; never
guess it or substitute another source. The stored identity represents the current
provider/device model, not separately verified external-account authentication.

The following is a template; set the profile, source ID and inclusive dates from
the authorized scope. All selected dates must have completed in Europe/Moscow.
One invocation may span at most 14 dates, only `daily_summary`, with the existing
chunk/request caps. Start with a small pilot and verify its evidence before a
larger separately authorized portion.

```powershell
uv run --locked healthcheck garmin-backfill --data-dir $ownerData `
  --start $startDate --end $endDate --stream daily_summary `
  --reacquire-unproven-daily-summary --garmin-source-id $garminSourceId --dry-run
```

Dry-run validates only request shape and makes no profile/auth/provider access;
it does not certify source existence or proof eligibility. Remove `--dry-run`
only for the authorized acquisition. Actual execution validates one complete
bounded proof snapshot under the operation lock before auth. Incomplete search,
original/spine integrity uncertainty, ambiguous latest evidence, invalid source
binding or current/future dates stop without provider calls. No cap is raised or
reset to bypass this failure. An existing receipt on an acquisition the native
reader cannot prove also blocks for separate diagnosis, even when its run is
failed/running/nonterminal. This mode requires unproven acquisitions to be
unreceipted. `--reprocess`, mixed streams and missing explicit
`--data-dir`/source are rejected.

Already proven latest acquisitions skip, including zero/null/missing/invalid
Steps outcomes. A successful fetch must bind the requested day and selected source
and commit its own immutable receipt. Check request counts, original hash/size,
returned-day binding, new observation/receipt, native completed-day reader and
unchanged old partial statuses. Same bytes reuse raw identity; they still need a
new acquisition observation. Repeat the same bounded request to verify resume
skips proven days without duplicate current records or additional calls.

Auth/permission, rate-limit, timeout or other per-day errors stop remaining days;
keep the report and committed receipts, without mass retry. For `reauth_required`,
the Owner runs the existing `garmin-auth --data-dir $ownerData` interactive recovery
above, resolving any provider MFA/captcha there, then resumes only the authorized
range. Do not reset checkpoints, rewrite old partial runs, reconstruct receipts or
use offline `garmin-reprocess` to certify historical fetches. Default backfill and
projection-version `--reprocess` retain their existing skip rules.


<a id="windows-uat"></a>

<a id="windows-uat--reusable-windows-start-and-safe-candidate-uat"></a>
## Reusable Windows start and safe candidate UAT

<a id="windows-uat--2-separate-runtime-data-directory"></a>
### 2. Separate runtime data directory

Set a UAT-only data dir outside Git, for example:

`HEALTHCHECK_DATA_DIR=%LOCALAPPDATA%\Health-Check\uat`

Do not reuse the production/profile database across branches.

<a id="windows-uat--3-dependencies--bootstrap"></a>
### 3. Dependencies / bootstrap

From the UAT checkout:

1. Install/sync dependencies with the project `uv` workflow.
2. Confirm the runtime directory is created under `HEALTHCHECK_DATA_DIR`, not inside the repo.
3. Confirm no private artifacts are staged in Git (`git status` clean of DB/photos/secrets).

<a id="windows-uat--4-mandatory-windows-fresh-start-smoke-ac-01"></a>
### 4. Mandatory Windows fresh-start smoke (AC-01)

Run:

`scripts/start.ps1`

Expectations:

- fresh empty runtime migrates cleanly;
- loopback UI and ingest listener start with the documented binds;
- no secrets printed.

**Status rule:** a required Windows fresh-start gate needs actual Windows evidence for its assigned code/profile. Linux/CLI substitutes do not establish that gate; use the active issue, not the old R01 release status.

<a id="windows-uat--4a-synthetic-demo-helper-developeruat-preparation"></a>
### 4a. Synthetic demo helper (developer/UAT preparation)

Use a new dedicated directory outside this checkout and outside any private profile. In PowerShell:

```powershell
$env:HEALTHCHECK_DATA_DIR = Join-Path $env:LOCALAPPDATA "Health-Check\r01-synthetic-demo"
uv run python -m healthcheck.cli seed-demo
```

The command creates a labelled synthetic six-month / 26-weigh-in profile through the accepted photo-import service path. Repeating it is a safe no-op after the manifest is validated. To explicitly rebuild that same marked synthetic profile:

```powershell
uv run python -m healthcheck.cli seed-demo --reset
```

An existing non-empty directory without the synthetic manifest is refused, including with `--reset`. This prevents a private-looking profile from being overwritten; choose a new empty directory instead. The reset removes only the marked demo database and `artifacts` tree, and leaves unknown files in place. The manifest and all runtime artifacts stay outside Git.

After seeding, run the mandatory owner start from this checkout (the helper does not replace AC-01):

```powershell
.\scripts\start.ps1 -DataDir $env:HEALTHCHECK_DATA_DIR
```

In another PowerShell window, run the read-only helper:

```powershell
.\scripts\uat-smoke.ps1
```

If the optional ingest listener is running, include its URL:

```powershell
.\scripts\uat-smoke.ps1 -IngestUrl "http://127.0.0.1:8121"
```

The helper prints only endpoint paths, statuses, and sanitized shape/readiness assertions. It checks UI/ingest liveness, dashboard/API reachability, ingest route isolation, and that the UI does not mount the openScale write route. It never prints response bodies or secrets and never reports AC-01 PASS.

Open the populated dashboard at `http://127.0.0.1:8120/`.

When finished, stop `start.ps1` with `Ctrl+C`, then remove only the dedicated synthetic profile after confirming its path:

```powershell
$demoDir = [IO.Path]::GetFullPath($env:HEALTHCHECK_DATA_DIR)
$expectedDemoDir = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Health-Check\r01-synthetic-demo"))
if (-not $demoDir.Equals($expectedDemoDir, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing cleanup outside the dedicated synthetic demo path" }
Remove-Item -LiteralPath $demoDir -Recurse -Force
```

Do not run that cleanup against a production or owner-private data directory.

<a id="windows-uat--5-loopback-ui-and-ingest-route-checks"></a>
### 5. Loopback UI and ingest route checks

- UI `/healthz` reports loopback-ui.
- Ingest `/healthz` reports ingest.
- Ingest does not expose dashboard/import/static/settings routes.
- UI does not expose openScale ingest write surface.

Record PASS / FAIL with exact URL and status code.

<a id="windows-uat--6-synthetic-dashboard--import-checks"></a>
### 6. Synthetic dashboard / import checks

Using synthetic fixtures only:

1. Import a synthetic batch → pending review (no implicit confirm).
2. Confirm/reject/edit paths as documented.
3. Dashboard shows raw + trend + coverage without inventing zeros.
4. If a stale/failed canonical recomputation is present, the dashboard shows the visible canonical warning banner.

<a id="windows-uat--7-owner-real-photo-uat"></a>
### 7. Owner real-photo UAT

Optional private photos on the owner machine only.

- Before the explicit upload, set `HEALTHCHECK_PHOTO_VISION_BASE_URL`,
  `HEALTHCHECK_PHOTO_VISION_MODEL`, and the provider API key in the owner
  process environment only. Do not put the key in `config.toml`, Git, or an
  issue/comment.
- Upload one ordinary Xiaomi S400 PNG/JPEG from the owner-private runtime
  profile. The expected first result is a failed-safe or pending review queue:
  successful extraction must create nonzero pending candidates, with zero
  confirmed/canonical measurements before owner action.
- Check that provider/model/prompt/schema and visible source/device/time
  provenance are shown without an authorization header, key, raw provider
  response, or absolute image path. Date-only evidence must remain date-only.
- If the provider is unavailable or returns malformed data, record the
  sanitized diagnostic and verify the immutable artifact remains reprocessable.
- Keep files under the UAT data dir, never in Git.
- Record PASS / FAIL / UNVERIFIED.

This procedure supplies reusable Windows/synthetic mechanics. Use the active issue for current acceptance; the original R01 release checklist is [historical](archive/uat/R01_OWNER_UAT.md). Do not activate optional live openScale, provider auth or import just to validate prose. Candidate UAT uses a disposable verified backup/restore clone, never Stable as a test fixture.


<a id="hrv-recovery-operations"></a>

<a id="hrv-recovery-operations--separately-authorized-copy-only-hrv-recovery"></a>
## Separately authorized copy-only HRV recovery

<a id="hrv-recovery-operations--separately-authorized-operator-procedure"></a>
### Separately authorized operator procedure

1. Obtain explicit authorization for an exact disposable profile, candidate SHA,
   date range and `hrv_status` only. Use supported consistent backup/restore;
   copying only a live DB without its WAL is insufficient. Never use Stable as
   the target. Verify clone provenance, ordinary non-reparse paths, schema and
   absence of another writer. Retain a pre-operation copy for rollback.
   The existing command has no source-ID selector: authorization must cover all
   saved HRV sources in this range, with their identities inventoried in advance.
   Otherwise STOP; do not remove other sources or silently expand authorization.
2. Record a private baseline manifest of original raw/artifact hashes and bytes,
   original acquisition observations, checkpoints and current projection. For
   every expected day, identify its own payload date, newest observation and
   weeklyAvg state/value. Include unchanged controls outside the range and in
   another surface/source. Do not publish personal values/IDs/dates on GitHub.
3. Begin with two adjacent dates and the existing `garmin-reprocess` command,
   explicit clone `--data-dir`, `--start`, `--end`, `--stream hrv_status`,
   `--max-observations` no greater than 140, and `--dry-run`. Check exact target,
   eligible/version-skipped/superseded counts and remaining budget. Dry-run
   enters runtime preparation/migration machinery: verify schema eligibility
   first; do not claim it is a general read-only command.
4. Only under the separate apply authorization, run that bounded operation on
   the same copy without `--dry-run`. Verify every dated current HRV value/state
   against its own original, not a window/receipt date. Check legacy retirement
   references and reasons. Any unexplained extra/missing day, source mix,
   rollback, stale overwrite or damaged provenance is STOP on the copy.
5. Repeat the identical operation: no new current duplicates, value drift or
   additional observations after convergence. Exercise bounded resume and compare
   its final per-day mapping with the expected mapping. Do not increase limits
   to bypass an unproven original. Inspect unresolved undated/malformed cases
   explicitly; a successful command is not proof all days were recovered.
6. Original bytes/raw rows/acquisition observations remain intact. Derivative
   observations and dated rows may be added, and a proven legacy current row may
   retire. Projection row-count growth is expected, not evidence of duplication.
   Outside-range/surface and unassigned-source controls, plus incremental/historical checkpoints,
   must match the baseline. Record integrity checks and their actual limits;
   a timeout is not a pass. Restore only the disposable copy if verification fails.

Expansion beyond the pilot, real recovery, provider reacquisition, Stable rollout
and Owner UAT each require their own assigned scope. This runbook grants none.

<a id="workspace-lifecycle"></a>

<a id="workspace-lifecycle--managed-lifecycle-format-1-and-cleanup-guards"></a>
## Managed lifecycle format 1 and cleanup guards

<a id="workspace-lifecycle--managed-workspace-lifecycle-and-cleanup"></a>
## Managed workspace lifecycle and cleanup

Worker enrollment/claim operations below remain format 1. The current source janitor
uses [recoverable root-container relocation and format 2 retirement](#workspace-retirement);
its states, recovery and no-Apply contract supersede the historical deletion-specific
janitor sections below. Existing deleting/deleted tombstones remain protected.

This is the v1 cooperative protocol used by `scripts/cleanup-workspaces.ps1`
and its matching native `.fs.cs` file. It adds no service, credentials, ACL or
execution-policy change. Installation and scheduling require separate acceptance;
a source change is not proof of the currently installed version or task state.

<a id="workspace-lifecycle--scope-and-state-contract"></a>
### Scope and state contract

Only **new standalone task clones** in the existing four immediate-child roots
can enroll. `Create` atomically creates a fresh empty child (fail if it exists)
and commits an active record under the existing project cleanup mutex. It cannot
adopt legacy folders. Clone into that empty directory, then `Bind` validates Git
topology, expected origin and physical root/GitDir identities. Clones with dependent
worktrees and all linked worktrees are preserved **before fetch**: v1 does not
coordinate ownership of the entire shared Git Common cohort.

All writers must `CheckActive` their bound active claim before work, `Pause` when paused,
`Resume` before any further writes or verification, and `Complete` only after
delivery when no more work is intended. A paused task retains ownership. Complete
requires the same owner and current ClaimId, a bound clone and a clean, private-free
snapshot. It is an explicit lifecycle transition, not a timer, PID test, `released`
string, PR state or a loose completed marker. Publication is proved afresh by the
janitor; completing a locally committed unpublished branch cannot permit deletion.

`Resume` accepts paused/completed for the same owner and current ClaimId, atomically
changes generation and ClaimId and clears completion. Save its returned ClaimId.
Active `Check` itself does not grant ownership to a second task; never share a token
or adopt another task's owner identity. `Check` reports the recorded state; writing
is permitted only when it is **active**, with the current token. `CheckActive`
rejects unbound, paused and completed records. The worker consumer below deliberately
does not expose diagnostic `Check`. There is no v1
ownership-transfer/adoption operation; use a fresh unique task clone for a new owner.

The lifecycle and janitor use one project mutex through their entire transaction.
Resume-first invalidates eligibility. Janitor-first commits `deleting` before the
first unlink, holds the mutex through removal, then commits `deleted`. Resume and
Create refuse both retired states, including after an interrupted/partial deletion.
An abandoned mutex permits inspection; it never resets ownership or tombstones.
A busy mutex rejects immediately; callers may retry later without stealing a claim.

This is cooperative coordination under the existing Owner workflow, not protection
against an arbitrary editor or a same-user attacker bypassing the protocol. The
matching accepted janitor/helper pair and participating clients must be deployed
together; do not run an old janitor against managed roots. A client without the
helper may only create a fresh unique **unmanaged** clone and record its owner once;
it must never resume/reuse an enrolled path. Such fallback clones remain ineligible
for automatic cleanup. Existing fallback markers are not migrated automatically.


<a id="lifecycle-records"></a>

<a id="lifecycle-records--persistent-lifecycle-records-failures-and-old-tombstones"></a>
## Persistent lifecycle records, failures and old tombstones

<a id="lifecycle-records--persistent-format-and-failure-handling"></a>
### Persistent format and failure handling

The fixed Ops directory holds `workspace-claim-<sha256-canonical-path>.state`.
Each v1 record is UTF-8 without BOM, LF-terminated, with exactly these ordered
`Name=Value` lines: Format, Path, RootId, GitId, Enrollment, Owner, Claim,
Generation, State, Head, Completed. Path is UTF-8 base64 of the canonical lexical
Windows path in invariant uppercase (one representation for case variants); identities
include volume/file index and creation timestamp. GitId is `-` until binding.
Enrollment/Claim are fresh lowercase 32-hex GUIDs; Generation is 1..999999999;
State is active, paused, completed, deleting or deleted. Completed is UTC ticks
and Head is a commit hash for completed/retired states, otherwise both are `-`.

The static `.git/workspace-enrollment.state` has exactly the first five fields.
It proves pairing to the external record, not completion. Unknown versions/fields,
duplicates, malformed records, missing registry/marker, copied markers, identity
changes and legacy `.git/codex-owner.json` (file or directory) all fail closed before fetch/delete.
Worktree pointers, aliases/reparse points and non-cache hardlinks remain protected.

No-follow bounded reads, pinned physical ancestors, fresh exclusive temporary files,
flush-to-disk and same-directory atomic write-through rename replace whole records.
State is never truncated in place. A process crash sees the old or new full record;
incomplete `.pending-*` files are not authority. Do not rename one into authority.
Create or Bind failing midway leaves an unmanaged/unbound/active folder preserved.
Leave uncertain/deleting records intact for manual read-only recovery assessment;
never clear a record, forge completion or re-enroll that path to make cleanup pass.
Tombstones remain outside deleted folders; use a new unique path for new work.

<a id="lifecycle-records--cleanup-guards-and-operation"></a>
### Cleanup guards and operation

Eligibility needs a matched **completed** record, unchanged completion HEAD and
physical root/GitDir identities, and at least seven days since **both** completion
and the newest relevant file/commit activity. Resume creates a new completion cycle.
All existing clean/untracked/ignored/cache, private/runtime, process, origin,
publication/local-ref and handle-bound deletion guards still apply. No broader
cache exception or root is introduced. Unknown, active, paused, dirty, unpublished,
private/runtime, backup/recovery and reparse material is preserved. Stable/Test,
staging, backups, Ops and unapproved workspaces are outside the allowlist.

The bounded `workspace-cleanup-latest.json` remains the structural run report. A
deletion error stops the sweep; its durable deleting record prevents automatic
Resume/retry. Dry-run does not change lifecycle state, but eligible completed clones
still fetch local origin tracking refs. No server/DB/process lifecycle is managed.

Rollback before deployment is simply to retain the currently installed version and
leave all schedules disabled/unregistered. After a separately approved deployment,
stop future scheduler invocations and preserve records for inspection; never roll
back to a janitor that ignores managed claims while retaining automatic Apply.
There is no undelete or automatic retirement reset. This candidate does not authorize
registration, installation, real Apply, runtime start/stop, DB writes or security changes.

Windows synthetic regressions cover both mutex winners, stale claims, paused tasks,
malformed/unknown/copied metadata, identity replacement, pending writes, durable
deleting/deleted states, abandoned mutex, shared worktrees, existing guards and an
actual eligible synthetic deletion. Fixtures are under an exact harness-owned temp
root; no Owner/runtime data is used.
The worker Create/Bind/CheckActive/Pause/Resume/Complete recipe is maintained in [Development](DEVELOPMENT_PROCESS.md#worker-checkout-workflow). Completion is distinct from recoverable retirement, and neither grants permanent-delete authority.


<a id="workspace-retirement"></a>

<a id="workspace-retirement--recoverable-workspace-retirement-v2"></a>
## Recoverable workspace retirement v2

The Integrator accepted this narrow contract on 2026-10-17 after the Owner chose a
separate recovery folder instead of Windows Recycle Bin. The existing Bin probes
and their counterexamples are historical research, not evidence for this consumer.
The original implementation candidate changed source only; its acceptance did not
itself install a helper, move real workspaces or enable a schedule. Installation
and scheduler receipts are separate, dated operational evidence. This chapter is
the reusable procedure, not a statement that Health or Finance is currently
uninstalled or awaiting activation. Consult the relevant project's current status
and accepted installation receipt before proposing another setup operation.

<a id="workspace-retirement--object-and-safety-boundary"></a>
### Object and safety boundary

Retirement relocates the same verified physical **root container with its actual
contents**. It is not an immutable tree snapshot, backup, free-space reclamation,
recursive deletion, or Windows Bin operation. No permanent delete, copy/delete
fallback, Shell, automatic restore or purge is provided. Recovery storage grows
until the Owner makes a separate decision; this task never removes its contents.

All existing eligibility guards remain: only newly enrolled, bound standalone
clones in fixed immediate-child roots; explicit completed state and at least seven
days since both completion and activity; current root/Git identities; clean,
published, private/runtime-free, inactive process state and recognized caches.
Active, paused, unknown, legacy, dirty, unpublished and shared worktrees preserve.
Stable/Main/Test/UAT/Owner/Ops/staging/backups/runtime/recovery are excluded.

Lifecycle, retirement, Recover and Restore hold the same project mutex throughout.
Resume-first invalidates eligibility. Retirement-first records durable intent and
v2 retiring state before releasing descendant handles. Root DELETE handle with
deny-delete sharing and real source/destination ancestor pins remain held through
the same-volume local fixed NTFS no-replace rename and post-inspection. No source
path is re-opened for the move. No destination is removed to make room.

Releasing descendants is deliberate: a root rename does not recursively act on
their handles or traverse a child junction. A noncooperative writer can still
change contents/membership, and Windows may refuse rename while other child
handles remain open. Refusal or uncertainty preserves and requires review, with
no fallback. This is cooperative coordination, not a new same-user security boundary.

<a id="workspace-retirement--observation-and-needs_review"></a>
### Observation and NEEDS_REVIEW

Before intent, retain a bounded metadata observation of the checked tree. After
rename confirm root identity and collect a bounded no-follow observation. Every
directory is inspected/pinned before enumerating its children; reparse, alias,
unsafe hardlink, inaccessible or over-limit material stops inspection without
traversing it. Known cache proof transfers only when the full metadata digest
matches the validated preflight; no new cache exception is inferred.

Observation files explicitly contain `NonSnapshot=true`. Relative paths,
identities, lengths, last-write timestamps and link counts form the digest; file
contents are not hashed. This does not prove unchanged bytes, a consistent point
in time, absence of a writer, or future immutability. Detected differences and
incomplete/unknown inspection are **NEEDS_REVIEW**. A matching observation is not
authority for any later deletion or purge. External modifications remain actual
container contents; relocation does not undo another process's writes.

Any observed change, unexpected original-path occupant, reparse/private marker,
inspection/observation bound, failure after intent or ambiguous result commits
`needs_review` in the journal and lifecycle. If a journal/state write itself fails,
the last prepared/retiring/restoring record still blocks all automatic consumers;
the caller reports error instead of claiming a new durable final state. Preserve
both objects when both locations exist. Never delete the new old-path occupant.
No automatic retry, restore, Resume or sweep of recovery occurs.

Every inspection, including explicit Recover and Restore preflight, retains a
verified root DELETE binding before its first descendant enumeration. A compatible
observation handle never substitutes for that binding. A closed journal is accepted
by ordinary consumers only after its fresh paused Claim/generation is committed
(or a later legitimate generation); closed journal plus old completed record stays
pending and cannot fetch, Resume or automatically retire again.

<a id="workspace-retirement--persistent-states-and-recovery"></a>
### Persistent states and recovery

Unchanged enrolled clients use lifecycle format 1. Retirement upgrades the target
record to format 2 with the same fields plus an ordered `Transaction` GUID.
Format 2 states are `retiring`, `retired`, `restoring`, `needs_review`; old v1
readers reject these records. The static enrollment marker remains format 1.
Deploy matching helper/janitor readers together; never deploy old automatic Apply.

The fixed Ops directory holds `workspace-retirement-<path-key>.state`, exact ordered
UTF-8/LF journal format 2: Format, Transaction, Path, Destination, RootId, GitId,
Enrollment, Owner, Claim, Generation, Head, Completed, BeforeDigest, AfterDigest,
BeforeObservation, AfterObservation, Phase, Issue, NextClaim, NextGeneration.
The destination is only `<fixed recovery root>\<transaction GUID>`. Phases are
prepared, retired, restore_prepared, restored, cancelled, needs_review. Claims are
local authority and must not be published. Closed previous journals are archived
before a new retirement cycle. Fresh observation names and pending files are not
lifecycle authority. Records use no-follow bounded reads and atomic flushed writes;
incomplete pending files are never promoted automatically.

`-Operation Recover -Workspace <original> -Owner <owner> -ClaimId <original claim>`
is explicit inspection/reconciliation, never a scheduled operation. It binds the
journal and record and inspects both fixed locations:

| Durable intent / observed object | Explicit Recover outcome |
| --- | --- |
| prepared, original only, expected identity/observation | cancelled; fresh paused claim, no move |
| prepared, recovery only, expected identity/observation | retired; no repeated rename |
| restore_prepared, original only, verified | restored; fresh paused claim |
| restore_prepared, recovery only | NEEDS_REVIEW; no restore retry |
| both/neither, changed identity/observation, existing NEEDS_REVIEW | preserve; NEEDS_REVIEW or reject |

An abandoned mutex permits this inspection, never a state reset. An API error does
not establish that nothing moved. Process-crash reconciliation is not a guarantee
against filesystem/media failure or a substitute for backup.

`-Operation Restore` is an explicit no-replace reverse rename from verified retired
root to the vacant original path. Intent and a fresh future Claim/generation are
durable first. The source root stays bound while descendants are released. Inspect
again after return; changes/uncertainty become NEEDS_REVIEW. A successful location
restore returns **paused**, not permission to write. The owner must Resume using
the new claim and CheckActive; changed enrollment/Git identities never acquire an
automatic new claim. NEEDS_REVIEW needs separate read-only assessment and a new
explicit recovery decision; this consumer has no override/adoption switch.

<a id="workspace-retirement--cli-and-bounds"></a>
### CLI and bounds

Scan remains default; `-Apply` is refused. `-Retire` is the only move switch.
Scan retains its existing completed-candidate fetch behavior (local Git metadata
writes), so it must not be described as a strictly read-only filesystem scan.
At most 200 tasks, 25,000 entries per task, depth 128, 4 MiB per observation and
8 KiB per journal/claim. A bound is a preserve/review result, never truncation
presented as a complete manifest. No raw Git errors, process commands, real data,
file contents or credentials enter the structural latest report.

<a id="workspace-retirement--acceptance-and-activation-plan"></a>
### Acceptance and activation procedure

Apply this procedure when a new installation or change is explicitly assigned.
Its presence here is not a pending task or a reason to repeat an accepted setup.

Validate synthetic eligibility, both mutex winners, root/path/reparse guards,
external content writes and new old-path occupants, destination/restore collisions,
double run, crash before/after both moves, explicit reconciliation and paused claim
issuance. Retain deliberate nonzero crash exits and actual abandoned-mutex evidence.
Review the frozen exact source/evidence independently; obtain exact CI. Old Shell
or historical immutable-tree results do not supply those passes.

After independent project acceptance, prepare the fixed same-volume recovery root
`D:\HealthCheck\recovery\workspaces`, install matching accepted source with rollback
copies while tasks remain absent/disabled, validate synthetic restore, and run a
fresh accepted-helper Scan. Do not label the historical 06:41Z scan as current.

Only after reviewing that scan may a separately accepted scheduler use:

- Name `Health-Check-workspace-retirement`; daily 12:00 machine local time.
- Current normal user, InteractiveToken/Limited, no password/credential grant,
  IgnoreNew and StartWhenAvailable; same existing project mutex.
- Windows PowerShell 5.1 hidden action:
  `powershell.exe -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File D:\HealthCheck\ops\workspace-cleanup\cleanup-workspaces.ps1 -Operation Scan -Retire -RetentionDays 7`.
- Structural log `D:\HealthCheck\ops\workspace-cleanup-latest.json`; durable claims,
  journals and bounded observations in the same Ops directory; moved containers in
  the recovery root. Recovery never appears among scan roots.
- Stop future invocations to roll back; preserve pending states and all containers.
  Never swap in an old janitor ignoring v2 claims or enable permanent Apply.

Finance requires its own accepted lifecycle consumer, fixed roots/recovery path,
project mutex, exact validation and Integrator acceptance. This Health plan is not
authority to install, merge, register a task or touch Finance runtime. Stable,
refresh and CBM are unchanged by this work.

<a id="stable-operation-decisions"></a>

<a id="stable-operation-decisions--stable-runtime-and-operation-decisions"></a>
## Stable runtime and operation decisions

<a id="stable-operation-decisions--stable-owner-runtime--owner-operations"></a>
#### Stable Owner Runtime / owner operations

- Private durable profile: `D:\HealthCheck\stable`; clean code/control: `D:\HealthCheck\main`; Ops: `D:\HealthCheck\ops`; disposable UAT and Worker roles follow [Owner Machine Layout](#machine-layout).
- Stable is long-lived, never reset as UAT. Verified backup/restore clones are separate; no direct SQLite grafting between profiles.
- Bounded backup/verify/restore retains checksum/integrity/atomic protections; a local archive alone is not off-site recovery proof. #148's practical verified Drive ZIP/restore is accepted; protected age publication remains optional.
- Dense selected Google HR uses civil-day partitioned resumable staging/bounded transient retries; instant/interval identity is path-free, with retained legacy observations.
- Provider operations and cutoff-bounded stale-run recovery share the runtime lock; no fabricated success/checkpoint reset. #132's no-stale/no-duplicate outcome is dated, not perpetual.
- Owner code/Ops is separate from GitHub main and Worker trees. Merges never auto-deploy.
- Comments navigation/timezone is in the daytime installed rollout; durable save/edit/persistence Owner UAT remains separate. UAT comments do not automatically become Stable history.

<a id="stable-operation-decisions--owner-refresh--collection-policy-operational-status"></a>
##### Owner refresh / collection-policy operational status

#214 proved an automatic/logon selected-stream run with Scheduler result 0 and
successful Garmin/Training/Google/wearables-sleep layers; it does not guarantee
future runtime duration, sleep-resume, exactly-once or perpetual availability.
#238 makes collection intent explicit/reversible: disabled HR is non-actionable
without false fresh/provider-empty labels; enabled failures remain visible and
re-enabling does not authorize broad backfill.
