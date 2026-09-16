# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in their release-specific documents and GitHub issues.

## Current canonical state

- Canonical branch: `main`
- Latest released major slice: **R05 — Garmin / Google wearable sleep agreement**
- R05 canonical SHA: `46e59327e394ae6dbc5a4ecdf42913200124b9e9`
- R05 exact-main CI: `35130647037` — SUCCESS
- R05 tracker: #106 — closed completed
- R05 closeout: [R05_RELEASE_CLOSEOUT.md](R05_RELEASE_CLOSEOUT.md)
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

## Next work

### Current bounded product focus

- #119 — deterministic period brief v1 (weight/sleep/activity/data-quality evidence packet + thin rendering).

### Residual maintenance

- #98 — bounded evaluation of `python-garminconnect` 0.3.12 → 0.3.15.
- #99 — reproduce/minimize the known order-sensitive OAuth test/global-state leak before fixing anything.

### R05 disposition (released)

R05/#106 closed on `main @ 46e59327…`. Strict `device_pair` / `family_pair` remain fail-closed. Provider-attribution evidence was insufficient for a canonical switch. `account_wearables_sleep_observations_v1` is exploratory/uncertain-only. #105 deferred/NOT_ELIGIBLE; Garmin remains canonical/default.

## Core engineering rules

- `main` is the only canonical release source.
- Issue = contract; worker prompt = role + exact SHA + gate/delta + STOP conditions.
- Workers do not self-accept or merge.
- Integrator independently reviews actual refs/diffs/CI.
- Real health data, screenshots, tokens, provider payloads and runtime DBs never enter Git/CI/worker workspaces.
- Provider boundaries stay fail-closed on unknown shapes.
- Missing/null/zero/unavailable/unknown remain distinct.
- Deterministic analytics own mathematics; UI/LLM explain results rather than reimplementing them.

## Useful docs

- [README](../README.md)
- [Product Vision](PRODUCT_VISION.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Decisions and Open Questions](DECISIONS_AND_OPEN_QUESTIONS.md)
- [Current Execution History](EXECUTION_HISTORY_CURRENT.md)
- [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md)
- [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md)
- [Agent Orchestration](AGENT_ORCHESTRATION.md)
- [Development Process](DEVELOPMENT_PROCESS.md)
