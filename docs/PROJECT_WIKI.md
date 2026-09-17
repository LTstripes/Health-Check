# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in their release-specific documents and GitHub issues.

## Current canonical state

- Canonical branch: `main`
- Latest released major slice: **R05 — Garmin / Google wearable sleep agreement**
- R05 release SHA: `46e59327e394ae6dbc5a4ecdf42913200124b9e9` (exact-main CI `35130647037` SUCCESS; #106 closed)
- Post-R05 deterministic brief checkpoint: `2c19ca968f84efb5e69c1a859ce6016939e617ca` (exact-main CI `35139999279` SUCCESS; #119 closed)
- CI maintenance implementation accepted on `integration/ci-feedback-v1 @ e7edf3d9c04f137a77f6345a183e87872bac62a7`; exact integration CI `35235216797` — SUCCESS
- R05 closeout: [R05_RELEASE_CLOSEOUT.md](R05_RELEASE_CLOSEOUT.md)
- CI maintenance closeout: [CI_MAINTENANCE_CLOSEOUT_2026-09-17.md](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- Prior R04 release merge: `bb5776e98d259cb6256c95bd49d400dc1238af61` (CI `34768452960` SUCCESS; #80 closed)

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

### Period Brief owner UX

- #127 — Period Brief local UI v1 over the accepted #119 packet;
- #133 — compact human source labels and summary hierarchy follow-up;
- #129 — Owner UAT / closeout on real local evidence after accepted UI work.

### Stable Owner Runtime / owner operations

- #132 — establish one durable cross-domain Stable Owner Runtime;
- #134 — one-command / optional scheduled Garmin + Google refresh;
- #136 — rebuild and persist the accepted R05 exploratory agreement from Stable Runtime evidence;
- #139 — converge the remaining Garmin Body Battery sync edge;
- #140 — supported recovery for stale `running` sync metadata.

### Completed post-R05 / maintenance

- #119 — deterministic period brief v1 — closed completed;
- #98 — `python-garminconnect` 0.3.12 → 0.3.15 — closed completed;
- #99 — Google auth/sync order-sensitive test hardening — closed completed;
- #123–#125 — CI feedback/reliability implementation — closed completed.

### R05 disposition

R05/#106 closed on `main @ 46e59327…`. Strict `device_pair` / `family_pair` remain fail-closed. Provider-attribution evidence was insufficient for a canonical switch. `account_wearables_sleep_observations_v1` is exploratory/uncertain-only. #105 deferred/NOT_ELIGIBLE; Garmin remains canonical/default. #105 is not actionable merely because it remains open; no Owner action is required unless future live evidence meets its gate.

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
- [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md)
- [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md)
- [Agent Orchestration](AGENT_ORCHESTRATION.md)
- [Development Process](DEVELOPMENT_PROCESS.md)
