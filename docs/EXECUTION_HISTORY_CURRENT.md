# Current Execution History

This is the compact current release history for fast handoff. The older verbose engineering log remains in [EXECUTION_HISTORY.md](EXECUTION_HISTORY.md) and Git/GitHub history. This file is maintained as the current release-to-release narrative.

No raw owner health values, identifiers, payloads, screenshots, credentials or private runtime artifacts belong here.

## R00 — architecture and process foundation

R00 established the product and engineering rules:

- single-user Windows-first local system;
- Python/FastAPI/SQLite WAL;
- immutable/source evidence separated from canonical selection and derived analytics;
- device/provider/input/algorithm provenance separated;
- deterministic analytics below UI/LLM;
- explicit coverage and missing/null/zero semantics;
- release integration branches with Integrator-controlled acceptance/merge;
- worker prompts pinned to exact SHAs and issues as the real contracts.

## R01 — Weight & Body Composition — released

Main outcomes:

- runtime + migrations + provenance core;
- Xiaomi screenshot/photo import with confirmation;
- openScale/openScale-sync contract;
- canonical selection and coverage;
- deterministic weight/body-composition analytics;
- owner dashboard and backup/restore.

Owner UAT exposed real defects that synthetic CI missed: visible provenance, production image-extractor wiring and Windows timezone data. All were repaired before release.

## R02 — Garmin ingestion/backfill — released

Main outcomes:

- protected Garmin auth/session reuse;
- typed normalization and persistence;
- incremental sync + trailing reconciliation;
- bounded resumable historical backfill;
- historical/incremental checkpoint isolation;
- exact completed rerun with zero provider calls.

The full historical owner backfill exposed live convergence defects in activities, heart-rate and Body Battery that short-window tests did not reproduce. Focused repair rounds preserved the same owner runtime and converged without resetting private state.

Released stable main recorded in the R02 closeout: `d3b2fa316242ac11a7ba5851fdc99656cdf8e534`.

## Pre-R03 hardening

Before analytics, the project made two contracts explicit:

- collection reconciliation/version-aware reprocessing;
- analytic metric/time/coverage identity + immutable evidence manifests.

This prevented R03 from building statistics on ambiguous provider fields or mutable current rows without reproducible inputs.

## R03 — deterministic Garmin analytics/dashboard — released

Delivered:

- scalar personal baselines, quantiles, robust trend/deviation;
- deterministic activity/cycling comparison;
- bounded lagged Spearman association primitives with explicit lag direction and coverage gates;
- read-only owner Garmin dashboard/query service;
- provider-native score wording without inventing a custom readiness/recovery score.

Owner UAT found a populated SQLite migration failure in the accepted pre-R03 chain. A focused FK-safe migration repair was required before the owner dashboard gate could proceed. R03 was released only after populated runtime migration and owner read-only UAT passed.

## R04 — Google Health ingestion — released 2026-09-13

### Contract / architecture phase

R04 first re-audited current provider truth instead of trusting earlier assumptions. Final accepted direction:

- Google Health API v4 only;
- Web Application/Web Server OAuth, not Desktop random-port OAuth;
- fixed registered loopback callback;
- exactly two read scopes for sleep and health metrics/measurements;
- explicit `google_*` ingestion/persistence layer over shared runtime/evidence primitives;
- query mode and `dataSourceFamily` are acquisition context, not source identity;
- `google-wearables` family is not automatic Fitbit-device proof;
- R05 owns cross-source agreement/canonical sleep.

### OAuth / capability

#85 implemented and proved the auth/capability boundary. Owner-live evidence showed:

- Web Application authorization works on the local Windows runtime;
- protected session reuse works;
- planned Google Health surfaces are callable;
- source/device/platform metadata exists on some populated responses;
- heart-rate pagination exists live;
- paired-device settings endpoint is intentionally unavailable under the narrow R04 scope set.

The Google Auth Platform project initially remained in Testing. Follow-up #94 proved final `In production` / External state and fresh protected re-consent/session reuse. Long-horizon refresh-token durability remains observationally `UNVERIFIED` until enough time elapses.

### Persistence / normalization / migration safety

R04 added additive Google persistence and typed normalization through Alembic `0010_google_typed_normalization`.

A separate migration-ancestry guard (#96) was added after review identified that the normal fresh-database path was not enough proof for a moving multi-release SQLite chain.

Final owner DB closeout proved:

- revision `0010_google_typed_normalization`;
- readiness true;
- WAL + FK enabled;
- `PRAGMA quick_check = ok`;
- 0 FK violations.

### Sync / live blocker #110

#88 implemented bounded incremental sync, historical backfill, coverage/checkpoints, exact completed-rerun skipping and explicit bounded refresh.

The owner heart-rate run exposed a real provider shape not covered by fixtures:

1. heart-rate pagination repeatedly hit the request/page ceiling and resumed correctly;
2. a later resumed request returned HTTP 200 but failed generic `shape_drift`;
3. diagnostic stage 1 split page-envelope drift from normalization drift;
4. live rerun proved the failure was the page-envelope path;
5. privacy-safe diagnostic stage 2 inspected only structure of already-persisted invalid evidence;
6. exact live shape proved: top-level object, `dataPoints` missing, `nextPageToken` absent;
7. current ProtoJSON semantics justified treating the proven omitted empty repeated field as an empty terminal list page;
8. focused repair accepted only that missing-collection/no-token LIST/RECONCILE case; null/non-array/unknown shapes remain fail-closed.

Accepted repair candidate: `52b0751890f9688cbf7399b3ddf0ff364146d714`.

Merged to R04 integration through PR #113; integration head became `406f4044ffb0d010c64a8635d402016ae916fc5a`.

Owner-live proof after repair:

- same heart-rate window completed as `confirmed_empty` with one provider call;
- exact rerun made **0 provider calls** and skipped completed coverage;
- one-day `daily_hrv` historical backfill succeeded;
- one-day explicit `daily_hrv` refresh succeeded and exercised reconciliation.

#110 and #88 were then closed completed.

### R04 release closeout

Release candidate: `406f4044ffb0d010c64a8635d402016ae916fc5a`.

- PR #114: `integration/r04-google-health` → `main`
- exact PR-context CI `34768197695`: SUCCESS
- release merge commit: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- exact post-merge `main` CI `34768452960`: SUCCESS
- tracker #80: closed completed

R04 release truth is recorded in [R04_RELEASE_CLOSEOUT.md](R04_RELEASE_CLOSEOUT.md).

## Lessons carried forward

- Owner UAT is not ceremony: it repeatedly found defects green synthetic CI could not prove.
- Provider shape diagnostics should distinguish structural failure classes early and remain privacy-safe.
- Exact completed-window rerun with zero provider calls is a powerful convergence proof.
- Family/query context must never be promoted into physical-device identity without explicit metadata.
- Populated-database migration checks belong in release gates, not only fresh-DB tests.
- `main` is the only release source; staging branches are temporary coordination tools.

## R05 — Garmin / Google wearable sleep agreement — released

Main outcomes:

- #100–#104 pairing/projection/persistence/statistics/report contracts;
- #122 exploratory uncertain account observations cohort, labeled exploratory-only;
- owner UAT/closeout #106 completed on canonical `main @ 46e59327e394ae6dbc5a4ecdf42913200124b9e9`;
- exact-main CI `35130647037` SUCCESS;
- strict legacy `device_pair` / `family_pair` fail-closed;
- provider-attribution evidence insufficient for canonical switch;
- #105 deferred / NOT_ELIGIBLE; Garmin remains canonical/default.

Sanitized closeout: [R05_RELEASE_CLOSEOUT.md](R05_RELEASE_CLOSEOUT.md).

## Post-R05 / #119 — deterministic period brief v1 — completed

Handoff checkpoint:

- accepted pre-maintenance canonical checkpoint `main @ 2c19ca968f84efb5e69c1a859ce6016939e617ca`;
- exact-main CI `35139999279` — SUCCESS;
- #119 closed completed.

Delivered (product, not a new major release number):

- deterministic weight/sleep/activity/data-quality period brief evidence packet with stable result hash;
- thin API/text/CLI rendering over that packet;
- accepted direct R05 sleep-report reuse and full activity inventory repairs.

Also closed completed (not residual backlog): #98 Garmin dependency upgrade; #99 Google auth/sync test hardening.

## 2026-09-16 to 2026-09-17 — CI feedback/reliability maintenance — #123–#126

### #123 — evidence/gating foundation

#123 made remote CI evidence inspectable and fail-closed rather than treating a green job label as the whole proof:

- exact workflow/ref/SHA/tree/attempt/lock provenance;
- retained JUnit/log/status/timing evidence and contradiction checks;
- safe task/PR supersession without collapsing canonical/integration commits into one concurrency slot;
- repair of the observed timestamp-sensitive privacy test flake.

Accepted candidate `e1767bbd6820f183b6e70e78c4f843bcbbd259af`; exact task CI `35183585714` SUCCESS; exact integration CI `35184385269` SUCCESS.

### #124 — balanced Linux lanes / material performance improvement

#124 replaced the dominant serial full-suite wait with quality plus three independent ordinary serial pytest lanes and a stable final `checks` aggregator. A checked manifest and independent collection/execution evidence reconcile exact nodeids/multiplicity; missing/overlapping/stale/substituted test inventory fails closed.

Accepted/integrated candidate `54ba37adc79dfb4cf0c5997a758f868a32d12af6`.

- task CI `35203141032` SUCCESS, about **2m13s**;
- integration CI `35207859309` SUCCESS, about **2m32s**;
- candidate inventory `881` exact nodeids, with `880 passed + 1` exact allowlisted Linux-side Windows-DPAPI skip.

The accepted pre-parallel full-run reference was about **5m02s**, so the material serial stall was removed. The Integrator explicitly stopped the performance campaign rather than adding xdist, fixture caching or micro-tuning for seconds.

### #125 — real focused Windows reliability

#125 added a small mandatory Windows job instead of a duplicate full Windows matrix.

Final accepted contracts:

- native Windows user-scoped DPAPI designated regression must actually execute and pass;
- real `scripts/start.ps1` launch on external synthetic paths containing spaces;
- real ingest-disabled and ingest-enabled loopback HTTP scenarios with route separation;
- bounded readiness/HTTP behavior;
- verified root PID + Name + CommandLine ownership;
- root-scoped `taskkill /PID <verified-root> /T /F`, never process-name-wide cleanup;
- post-cleanup root/ports/runtime verification;
- Windows schema-v2 evidence consumed by final `checks`.

The real hosted runner exposed several lifecycle races. After four distinct cleanup-edge failures, Integrator stopped the patch-by-patch approach and required a bounded root-tree redesign. The final port-state bug was corrected with a deterministic loopback bind/listener probe rather than `ConnectAsync` refusal inference.

Final candidate `e7edf3d9c04f137a77f6345a183e87872bac62a7`.

- exact task CI `35232981949` SUCCESS;
- native designated DPAPI: `1 passed / 0 skipped`;
- exact integration CI `35235216797` SUCCESS in about **2m48s**;
- final integration gate: `checks PASS: 890 exact nodeids reconciled across all mandatory jobs` and `WINDOWS_SMOKE_EVIDENCE: PASS`.

Independent final review used Grok 4.6 as a different model family; Integrator separately re-read code/evidence/refs/CI before ACCEPT. #125 closed completed.

### Net result

Representative accepted wall time moved from about `5m02s` to about `2m48s` with focused Windows coverage included: approximately **44% lower remote feedback wall time** while verification became materially stronger.

Quality improvements are more important than the seconds:

- exact test inventory completeness;
- same-run provenance-bound evidence;
- fail-closed final aggregate verdict;
- real native Windows DPAPI;
- real Windows PowerShell/HTTP/runtime/cleanup behavior;
- a clearer development rhythm: targeted iteration → one stabilized candidate gate → exact integration gate → exact main gate.

See [CI_MAINTENANCE_CLOSEOUT_2026-09-17.md](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md).

### #126 — server-side enforcement blocked by repository capability

#126 verified that the private repository currently cannot enable the desired server-side branch protection/required-check policy under the available GitHub capability. Rulesets return the explicit private-repository GitHub Pro capability 403; an Owner-authorized admin-token review confirmed the same plan/capability blocker for classic protection.

Decision:

- keep repository private;
- do not purchase/change plan as an implicit engineering action;
- do not simulate protection with workflow YAML;
- keep #126 open `BLOCKED / OWNER DECISION REQUIRED`.

Until capability changes, exact-SHA final `checks: SUCCESS` is a mandatory manual Integrator gate before advancing integration or `main`. Green constituent lanes are insufficient; force-push/deletion of canonical/integration history remains process-prohibited.

## 2026-09-17 to 2026-09-21 — Stable Owner Runtime / operations closeout

The post-R05 runtime work changed the project from release-specific owner profiles into one durable cross-domain Owner Runtime.

### #132 reconstruction

Accepted owner data profile: `D:\Garmin\HealthCheck-Stable`.

The Stable profile preserved the accepted historical Weight/body-composition base. Garmin and Google were reconstructed through supported auth/sync/backfill paths rather than SQLite grafting. #136 later rebuilt the accepted exploratory R05 agreement from Stable's own persisted evidence; exact rerun reused the same semantic run.

### Provider convergence and live-only defects

Real Stable data exposed several defects that synthetic tests had not reproduced:

- #138: dense Google historical HR pagination needed durable cursor ownership across planner chunks;
- #139: exact duplicate Body Battery timestamp+level samples needed narrow semantic coalescing before persistence;
- #150: dense normal Google HR refresh needed deterministic civil-day partitioning;
- #154: transient provider 500/502/503 responses needed bounded retry classification;
- #156: exact refresh reruns exposed response-position/path-driven semantic identity churn even though key-level duplicate checks remained zero.

#156 became the deepest semantic repair. Read-only diagnosis showed most new rerun HR rows matched older source/timestamp/value/external evidence but differed in path/index-derived identity. The frozen repair introduced path-free instant/HR-interval identity, repository-driven legacy retirement/migration, correction ordering by provider epoch and fail-closed same-epoch ambiguity. Live clone rehearsal and Stable migration both completed with zero conflicts; second migration was a no-op; canonical current instant duplicate groups became zero and remained zero on rerun/resume.

### Backup durability

A fresh pre-#156 recovery point initially failed because the Stable SQLite member had grown beyond the accepted 4 GiB member cap. #158 raised only the member envelope to 6 GiB while retaining the 8 GiB total expanded cap and all existing ZIP64/checksum/integrity/atomic-restore protections.

A fresh real backup then completed, independently verified and restored into a disposable external clone. That clone matched Stable's structural state and was used for the #156 migration rehearsal.

### Routine refresh final gate

The first full post-migration owner-refresh succeeded. A second exact-window run hit one bounded provider interruption on the newest HR day but did not recreate semantic churn: the failed staging run accepted no typed records and retained a resumable cursor.

Targeted continuation through the same production helper then succeeded, cleared the cursor, inserted zero new semantic records, preserved zero duplicate logical groups and left agreement/#140 state unchanged. #134/#150/#156 were closed without forcing another expensive seven-day replay solely for a second top-level exit code.

### #140 orphan recovery

Two historical SyncRun rows remained `running` after interrupted owner processes. #140 added a shared profile-scoped external-runtime operation lock plus an explicit cutoff-bounded dry-run/apply maintenance command using existing terminal `failed` semantics.

Owner-live dry-run saw exactly two stale rows. Apply recovered exactly two; repeat apply was `0/0/0/0`. No source/checkpoint/artifact cleanup or manual SQL was used.

### Stable closeout

#132 is closed completed. Final read-only structural closeout proved healthy SQLite/migration state, Weight/Garmin/Google/agreement presence, no running SyncRun rows, no canonical instant duplicate groups and no unexpected provider/source-family classes. The earlier broad Google acquisition was retained as valid owner evidence rather than pruned.

Accepted/live-tested Stable integration head: `0b05a80749e3ef0d2fa736778baa49cc23f18a61`; exact CI `35581607069` SUCCESS.

Important repository note: at the Stable closeout checkpoint, `main @ 6f21eeacf80491f73bcf9c5b5411eba1922dd1a4` and the Stable integration line diverged from `2c19ca968f84efb5e69c1a859ce6016939e617ca`. Stable runtime acceptance therefore does not itself make its branch canonical Git history.

## Current handoff / next work

### First: reconcile accepted repository lines

Before new shared implementation, re-read and deliberately reconcile:

- current `main` (re-read from GitHub; the Stable closeout reference was `6f21eeacf80491f73bcf9c5b5411eba1922dd1a4`);
- `integration/stable-owner-runtime @ 0b05a80749e3ef0d2fa736778baa49cc23f18a61`;
- `integration/period-brief-ui-v1 @ a1d4e4c68674305b78ad3acee8140e96ba5a2e92`.

Preserve accepted deltas and rerun exact-SHA gates; do not blindly stack work on one divergent branch.

### Then: Period Brief correctness / UX / UAT

- #146 — fix real producer/consumer DTO drift, effective analytical window truthfulness and honest activity emptiness;
- #133 — compact source labels / summary hierarchy / deterministic deduplication;
- #129 — Owner UAT/closeout using a disposable backup-restored clone of Stable;
- #127 closes with successful Period Brief UI/UAT.

### Separate future work

- #147 source freshness;
- #148 off-site disaster recovery;
- #153 Xiaomi S400/openScale live E2E verification;
- #160 Garmin-native training analytics discovery/persistence/UI.

#126 remains blocked on private-repository GitHub protection capability. #105 remains deferred/NOT_ELIGIBLE; Garmin stays canonical/default for sleep.
