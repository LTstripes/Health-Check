# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in their release-specific documents and GitHub issues.

## Current canonical state

- Canonical Git branch: `main`
- Current canonical checkpoint for this handoff: `main @ b887fceceb85931ad8ead9423c0f86e0cac09291`
- Exact-main CI: `35608281796` — SUCCESS
- Historical Stable-line divergence checkpoint: `6f21eeacf80491f73bcf9c5b5411eba1922dd1a4`; keep it only as lineage evidence.
- Current `main` must always be re-read from GitHub before launch/integration; do not encode a docs-merge SHA as permanent architecture truth.
- Latest released major slice: **R05 — Garmin / Google wearable sleep agreement**
- R05 release SHA: `46e59327e394ae6dbc5a4ecdf42913200124b9e9` (CI `35130647037` SUCCESS; #106 closed)
- #119 deterministic period brief v1: completed at `2c19ca968f84efb5e69c1a859ce6016939e617ca` (CI `35139999279` SUCCESS)
- Stable Owner Runtime: **accepted/live-proven**, #132 closed
- Canonical owner data profile: `D:\Garmin\HealthCheck-Stable`
- Stable live-tested code line: `integration/stable-owner-runtime @ 0b05a80749e3ef0d2fa736778baa49cc23f18a61` (CI `35581607069` SUCCESS)
- Period Brief presentation line: `integration/period-brief-ui-v1 @ a1d4e4c68674305b78ad3acee8140e96ba5a2e92` (#131 integrated)
- Important: Stable integration and the pre-closeout main line diverged from merge base `2c19ca968f84efb5e69c1a859ce6016939e617ca`; repository reconciliation is the next integration gate, not an implicit fast-forward.
- R05 closeout: [R05_RELEASE_CLOSEOUT.md](R05_RELEASE_CLOSEOUT.md)
- Stable Runtime closeout: [STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md](STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md)
- CI maintenance closeout: [CI_MAINTENANCE_CLOSEOUT_2026-09-17.md](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)

## What the product can do today

### Weight / body composition

- import and confirm Xiaomi screenshots/photos;
- preserve source/device/algorithm provenance;
- accept the openScale/openScale-sync live contract;
- calculate deterministic weight/body-composition trends;
- show the local weight dashboard.

### Garmin

- protected owner-assisted session reuse;
- incremental sync + historical backfill;
- coverage/checkpoints/reconciliation;
- deterministic scalar baselines/trends;
- activity/cycling comparison;
- bounded lagged associations;
- read-only owner Garmin dashboard.

### Google Health

- Web Application OAuth with a fixed registered loopback callback;
- external-runtime DPAPI-protected Google auth/session state;
- read-only sleep + health-metrics scopes;
- typed Google source/raw/current evidence;
- bounded incremental sync;
- historical backfill;
- explicit bounded refresh/reconciliation;
- coverage/checkpoint/idempotency semantics;
- privacy-safe structural diagnostics.

### Cross-domain reporting

- deterministic period brief v1 over weight, sleep, activity and data-quality/coverage evidence;
- stable result hash and reproducible evidence packet;
- thin API/text/CLI rendering without reimplementing analytics;
- direct reuse of the accepted R05 sleep report and complete bounded activity inventory semantics.

### Live-accepted Stable Owner Runtime

Pending repository-line reconciliation, the accepted Stable integration adds/proves the normal long-lived owner operating model:

- one persistent private profile for Weight, Garmin, Google and exploratory agreement evidence;
- supported large-profile backup → verify → restore into disposable clones;
- bounded one-command Garmin + Google owner refresh;
- dense Google HR daily-partition refresh and safe resumable continuation;
- path-free Google instant/interval semantic identity with repository-backed legacy migration;
- shared external-runtime operation locking and explicit stale SyncRun recovery;
- no current canonical instant duplicate groups and no remaining stale `running` SyncRun rows in the accepted Stable profile.

Stable is owner data, not Git state. It is never reset for release UAT; UAT uses a disposable restored clone.

## R04 live proof

The owner-live gate proved:

- Google Auth Platform `In production` / External;
- two required read scopes granted, no missing scope;
- protected re-consent and immediate session reuse;
- live capability across planned Google Health surfaces;
- heart-rate pagination/resume;
- terminal-empty provider envelope repair (#110);
- completed heart-rate window exact rerun with **0 provider calls**;
- bounded historical `daily_hrv` backfill;
- explicit `daily_hrv` refresh/reconciliation;
- populated private DB integrity at Alembic `0010_google_typed_normalization`, `quick_check=ok`, FK violations `0`.

No raw owner health data or secrets are part of the repository.

## Source-attribution rule that matters for R05

`dataSourceFamily`, `list/reconcile/rollUp/dailyRollUp` and broad `google-wearables` family membership are acquisition context, not proof of one physical Fitbit device.

R05 uses two different legacy cohorts (plus an exploratory uncertain account cohort):

- `fitbit_device` / `device_pair`: only explicit persisted source/device metadata can qualify;
- `google_wearables_family` / `family_pair`: exploratory only, never sufficient for a canonical-source switch.

This prevents the project from accidentally comparing Garmin against a mixed Pixel Watch/Fitbit/family aggregate and calling it Fitbit agreement.

## Engineering reliability / CI

The bounded #123–#125 maintenance track is complete.

What changed:

- evidence became provenance-bound and fail-closed (#123);
- one long Linux path became three independent balanced serial lanes plus quality (#124);
- the final `checks` job reconciles the exact expected Linux nodeids/multiplicity rather than trusting subset job labels;
- a focused Windows runner now executes real native DPAPI, real `start.ps1`, loopback UI/ingest scenarios, path-with-spaces runtime handling and verified root-tree cleanup (#125).

Representative remote feedback improved from about **5m02s** to about **2m48s** with the Windows gate included — roughly **44% less wall time** while coverage became stronger. The accepted final integration gate reported `890 exact nodeids reconciled across all mandatory jobs` and `WINDOWS_SMOKE_EVIDENCE: PASS`.

Do not continue CI optimization just to shave seconds. Reopen performance work only if a new measured material bottleneck appears.

### Required-check enforcement limitation

#126 remains **BLOCKED / OWNER DECISION REQUIRED**. This private repository currently has no server-side branch protection/required-check enforcement under the available GitHub capability. The repository stays private; no billing/plan change is implied by engineering work.

Until that changes, the manual Integrator gate is mandatory:

- exact target SHA must have final `checks: SUCCESS` before advancing integration or `main`;
- constituent green jobs alone are insufficient;
- only the Integrator advances shared/canonical refs after ACCEPT;
- force-push/deletion of integration/canonical history is process-prohibited.

## Current work

### 1. Repository-line reconciliation

Before new shared product work is stacked, reconcile current `main @ b887fcec…`, accepted `integration/stable-owner-runtime @ 0b05a807…`, and accepted Period Brief presentation line `integration/period-brief-ui-v1 @ a1d4e4c…`. Preserve accepted semantics and rerun exact-SHA gates; do not blindly merge divergent histories.

### 2. Period Brief correctness / owner UX / UAT

- **#146** — repair confirmed producer/consumer DTO drift, effective-window truthfulness and honest activity emptiness;
- **#133** — compact human source labels, summary hierarchy and deterministic deduplication;
- **#129** — Owner UAT/closeout using a disposable clone of Stable;
- **#127** closes with successful UI/UAT closeout.

### 3. Separate future owner-value work

- #147 — metric-aware source freshness/silent-source signal;
- #148 — off-site portable backup / disaster recovery;
- #153 — real Xiaomi S400 → openScale → Stable E2E verification;
- #160 — Garmin-native training/load/status/recovery discovery and later bounded persistence/UI.

### Completed post-R05 / operational work

#119, #132, #134, #136, #138, #139, #140, #141/#158, #150/#154/#156, #98/#99 and #123–#125 are completed. #126 remains **BLOCKED / OWNER DECISION REQUIRED** because server-side private-repository required-check enforcement is unavailable under the current GitHub capability.

### R05 disposition

Strict `device_pair` / `family_pair` remain fail-closed. `account_wearables_sleep_observations_v1` remains exploratory/uncertain-only. #105 is deferred/NOT_ELIGIBLE; Garmin remains canonical/default.

## Core engineering rules

- `main` is the only canonical release source.
- Issue = contract; worker prompt = role + exact SHA + gate/delta + STOP conditions.
- Workers do not self-accept or merge.
- Integrator independently reviews actual refs/diffs/CI.
- Real health data, screenshots, tokens, provider payloads and runtime DBs never enter Git/CI/worker workspaces.
- Provider boundaries stay fail-closed on unknown shapes.
- Missing/null/zero/unavailable/unknown remain distinct.
- Deterministic analytics own mathematics; UI/LLM explain results rather than reimplementing them.
- During implementation, use targeted checks; stabilized candidates/integration/main receive exact remote gates.

## Useful docs

- [README](../README.md)
- [Product Vision](PRODUCT_VISION.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Decisions and Open Questions](DECISIONS_AND_OPEN_QUESTIONS.md)
- [Current Execution History](EXECUTION_HISTORY_CURRENT.md)
- [Stable Owner Runtime Closeout](STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md)
- [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md)
- [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md)
- [Agent Orchestration](AGENT_ORCHESTRATION.md)
- [Development Process](DEVELOPMENT_PROCESS.md)
