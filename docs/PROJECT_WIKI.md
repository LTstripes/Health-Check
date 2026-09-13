# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in their release-specific documents and GitHub issues.

## Current canonical state

- Canonical branch: `main`
- Latest released major slice: **R04 — Google Health ingestion**
- R04 release merge: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- R04 post-merge CI: `34768452960` — SUCCESS
- R04 tracker: #80 — closed completed
- R04 closeout: [R04_RELEASE_CLOSEOUT.md](R04_RELEASE_CLOSEOUT.md)

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

R05 uses two different cohorts:

- `fitbit_device` / `device_pair`: only explicit persisted source/device metadata can qualify;
- `google_wearables_family` / `family_pair`: exploratory only, never sufficient for a canonical-source switch.

This prevents the project from accidentally comparing Garmin against a mixed Pixel Watch/Fitbit/family aggregate and calling it Fitbit agreement.

## Next work

### Small post-R04 maintenance

- #98 — bounded evaluation of `python-garminconnect` 0.3.12 → 0.3.15.
- #99 — reproduce/minimize the known order-sensitive OAuth test/global-state leak before fixing anything.

### R05 — Garmin / Google wearable sleep agreement

Design is frozen in #97.

Implementation graph:

1. #100 — pairing / source eligibility
2. #101 — comparable sleep projection
3. #102 — immutable/versioned agreement runs and replay
4. #103 — statistics + 14/42 gates
5. #104 — report / overlays
6. #105 — optional versioned canonical-source rule after sufficient live `device_pair` evidence
7. #106 — owner UAT / closeout

R05 can succeed with an exploratory agreement report even if there is not yet enough evidence to change the canonical source.

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
- [Agent Orchestration](AGENT_ORCHESTRATION.md)
- [Development Process](DEVELOPMENT_PROCESS.md)
