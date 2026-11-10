# Stable release tooling v2

Run `release.py` with Python 3.12+ from either Windows PowerShell 5.1 or pwsh 7.
The selected release environments provide Alembic and Health-Check; the operator
CLI itself uses the standard library. There are no network calls in preparation.
Git ancestry uses the already fetched `origin/main`; refresh/validate that ref and
inspect exact CI evidence before preparing a candidate.

```powershell
python scripts/stable_release/release.py prepare <full-sha> --config <private-config.json> --ci-run-id <run-id/attempts/N> --manifest <new-candidate-directory/manifest.json>
python scripts/stable_release/release.py activate <new-candidate-directory/manifest.json>
```

Preparation never switches services, edits consumers, creates a backup or migrates.
Use `--strict` to require the strict route. There is no force-code-only option.
Keep the candidate directory private: the manifest includes consumer text and local
paths. Use one new directory per attempt; existing manifests/attempts are refused.
The manifest's directory must already exist. The tool does not install checkouts
or dependencies. Do not use an Owner profile for development/testing.

## Inputs

Copy `config.example.json` to an external private directory and replace every
placeholder. Paths must be absolute and canonical. Both old and new release trees
must be clean, detached at their exact SHA, with installed `.venv` environments.
The candidate directory is `releases_root/stable-code-<sha8>`. Keep the versioned
tooling location available: the new pointer's `ui_start_script` references its
`StartStable.ps1`. No per-release PowerShell or Python generator is needed.

`ci_receipt` is a local, operator-supplied normalization of inspected exact-candidate
CI results, not a tool-issued attestation. Do not synthesize green status without
inspecting the run. All four jobs must belong to that SHA and run attempt:

```json
{
  "status": "PASS",
  "sha": "<40-character-lowercase-target-sha>",
  "run_id": "<run-id/attempts/N>",
  "jobs": {"quality": "success", "test": "success", "windows-smoke": "success", "checks": "success"}
}
```

`recovery_receipt` is the existing verified weekly recovery-point record, normalized
to the following fields if its original wrapper uses other names. The tool trusts
the prior verification receipt and checks archive accessibility, profile/schema,
timestamp and declared SHA-256; it does not reread/hash the full archive:

```json
{
  "status": "PASS", "verified": true,
  "profile": "<canonical-profile-path>",
  "path": "<existing-verified-backup-path>",
  "utc": "<backup-snapshot-time-in-UTC>",
  "sha256": "<64-character-lowercase-archive-sha256>",
  "schema": "<installed-revision>"
}
```

Code-only permits an age up to **8 days**, inclusive. Future timestamps fail.
Strict requires a recovery point no older than **24 hours**, additionally bound by
`candidate_sha`, and a `rehearsal_receipt` no older than 24 hours:

```json
{
  "status": "PASS", "candidate_sha": "<target-sha>",
  "profile": "<original-profile-path>",
  "from_schema": "<installed-revision>", "to_schema": "<target-head>",
  "recovery_sha256": "<same-backup-sha256>", "utc": "<UTC-rehearsal-time>"
}
```

Rehearsal PASS represents the separately completed supported backup/restore,
clone migration, integrity, foreign-key and applicable UAT gates; this tool does
not perform a rehearsal or infer it from a schema number. The 24-hour strict
freshness bound is the v1 implementation's conservative definition of "fresh".

`old_ui_binding` and its receipt must identify the **currently loaded run**, using
the actual binding in that process's command line. Autostart creates a fresh run
binding; the pointer's `ui_binding` remains its reusable template and is not proof
of the current PID/run. If `old_ui_binding` is omitted, it defaults to the pointer
template, which only works when that template is the actual loaded binding.
Rollback restores the original pointer template and records its fresh actual run
binding in the activation receipt; use that observation for a later preparation.
The new UI binding
uses the existing binding fields plus `schema` and `runner_version: 1`:

```json
{
  "code": "<candidate-checkout>", "sha": "<target-sha>",
  "profile": "<same-profile>", "schema": "<target-head>", "port": 8120,
  "head_file": "<candidate-checkout>/.git/HEAD",
  "runner_version": 1, "run_id": "<unique-run-id>",
  "receipt": "<unique-run-id>.json", "stop_file": "<unique-run-id>.stop"
}
```

Receipt/stop names must be local filenames. New receipt/stop files must not exist.
`mcp_binding` and `old_mcp_binding` are supported assistant operator bindings,
including their exact code/runtime/database identities and schema heads. Preparation
validates those identities with each release's interpreter, without opening the
profile for writes. Existing helpers for enrolling a binding remain unchanged.

Seven consumers are required by role. Default `mode: "legacy-rewrite"` preserves
compatibility. After the one-time migration, set each migrated nonpointer entry
to `"mode": "pointer-reading"` and remove its `replacements`. Such entries are
excluded from manifest text snapshots, drift checks, writes and rollback. The
active-pointer role must remain legacy-rewrite: it is always published structurally.
Unknown modes or replacements on skipped entries fail closed. In legacy mode,
code path (including JSON-escaped paths),
SHA and changed schema are rewritten in memory; the pointer is updated structurally.
Per-consumer `replacements` cover old ops-folder names, old rollback-directory
references and the weekly binding filename when needed. Put literal escaped text
in replacements for JSON consumers. The prepared weekly recipe must select the
new MCP binding; the binding is checked structurally, including code identity and
schema heads. Review the manifest's exact before/after texts before activation.

## Activation and failures

The tool rechecks all preparation evidence, hashes, installed pointer and revision
under the autostart mutex (`Local\HealthCheckAutostart`) and the profile's existing
external-runtime operation lock. Active refresh/backup/migration processes cause
refusal. It never changes Task Scheduler. Tests may select a different mutex via
`autostart_mutex` and override UI/MCP ports; real autostart uses the default mutex.

UI and MCP must both be identifiable by listener PID, creation time, executable,
exact binding argument and (UI) loaded-run receipt. Unavailable CIM/listener identity
fails closed. Legacy nonpointer files are written in place to retain ACLs.
Windows `ReplaceFileW` publishes the validated pointer atomically and preserves
its ACL and original file in `active-code.previous.json`.

Code-only never invokes migrate. On failure after stopping, the tool stops candidate
processes, restores the pointer and rewritten legacy consumers, restarts both old services using a fresh
UI run binding, and verifies both. The previous pointer bytes are restored exactly;
the fresh rollback UI binding is recorded in `activation.json`. Strict invokes the
supported CLI migrate; once migration is attempted, even a partial failure leaves
services stopped with diagnostics for the Owner. No DB restore/downgrade runs.
Before a migration attempt, strict failures use the same safe code rollback.

Smoke checks verify UI `/healthz` (new SHA and run ID), one configured page, actual
MCP process/binding plus authenticated MCP initialize, and the database revision.
The gateway token comes exclusively from `HEALTHCHECK_MCP_GATEWAY_TOKEN`. HTTP
bodies, authorization headers and subprocess output are never written to receipts
or logs. MCP smoke records only stage status and elapsed seconds. Launches are
hidden on Windows with stdout/stderr discarded. No credential is a config field.

`activation-started.json` prevents automatic retries after a crash; `activation.json`
records PASS/FAIL, stages, durations and bounded diagnostic codes. A lock refusal
happens before an attempt starts and does not overwrite another attempt's receipt.
Power loss/process termination cannot guarantee in-process rollback; preserve all
evidence and reconcile the pointer/services before any manually authorized retry.
This tool does not disable scheduled writers: after a strict failure, the Owner
must keep automation stopped while diagnosing/recovering the profile.

## Stable pointer entry points

Install `consumers.py`, `release.py` and `probe.py` together at a stable Ops path.
Use a separately installed Python 3.12+ as bootstrap, not a release-specific venv.
Copy `consumers.example.json` to a private config and select explicit paths:

```powershell
& $BootstrapPython -I -B D:\HealthCheck\ops\stable-release\consumers.py resolve-active --config D:\HealthCheck\ops\stable-release\consumers.private.json
& $BootstrapPython -I -B D:\HealthCheck\ops\stable-release\consumers.py run-owner-refresh --config D:\HealthCheck\ops\stable-release\consumers.private.json
& $BootstrapPython -I -B D:\HealthCheck\ops\stable-release\consumers.py run-weekly-backup --config D:\HealthCheck\ops\stable-release\consumers.private.json
```

Each command reads the pointer once. Canonical checkout and venv paths must be
inside `releases_root`; UI/MCP bindings intentionally live outside it in Ops.
Resolution validates the full SHA against Git HEAD, existing venv, configured
profile, UI code/SHA/profile/schema/port/head, and MCP code/runtime/database/schema
identities with that release's interpreter. No profile is created or migrated.
The pointer now includes `mcp_binding`; preparation writes it into both pointer
and manifest, and checks any existing old pointer value against `old_mcp_binding`.
Initial legacy pointers may omit it until their one-time enrollment.

Resolution failure always prints `active_pointer_invalid` and exits **2**, without
starting work or selecting a fallback. `--check-only` prints the resolved snapshot
without refresh/backup. Later launch/output failures print `active_work_failed`
and exit **3**; ordinary child exit codes are preserved. Output is checked for the
environment gateway token before either stream or a refresh log is written.
JSON is BOM-tolerant on read and UTF-8 without BOM on publication; rollback retains
the exact original bytes, including any historical BOM.

Refresh preserves the seven-day window, Google Steps catch-up, eight streams,
optional `google-hr.enabled` toggle, profile logs and the CLI's operation lock.
Weekly preserves the nonblocking `Global\HONORHealthDataOnlyBackup` mutex, waits
for its exact child without a timeout and passes `--no-restore-rehearsal`.
Its one-time migrated local backup reads `HEALTHCHECK_RELEASE_CODE`,
`HEALTHCHECK_RELEASE_SHA`, and `HEALTHCHECK_DATA_DIR` from the pinned parent snapshot;
it never rereads the pointer. No archive, retention or backup semantics change.

Scheduled tasks execute the stable bootstrap/entry/config with an explicit stable
Ops WorkingDirectory. The child WorkingDirectory is the resolved release checkout.
See [the exact one-time migration and rollback plan](../../docs/OWNER_OPERATIONS.md#stable-pointer-migration).
Do not change local files or Task Scheduler as part of code implementation.
