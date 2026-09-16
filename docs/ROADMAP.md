# Health-Check Roadmap

The roadmap is organized as usable vertical releases. Each release must work locally on Windows, preserve source evidence, and remain reproducible without live provider access in CI.

Future ideas that are not committed to a release live in [Backlog Ideas](BACKLOG_IDEAS.md).

## Current state

Released to canonical `main`:

- **R01** — Weight & Body Composition
- **R02** — Garmin ingestion and historical backfill
- **R03** — deterministic Garmin analytics and owner dashboard
- **R04** — Google Health API v4 ingestion, sync/backfill/refresh and owner-live release proof
- **R05** — Garmin / Google wearable sleep agreement (exploratory closeout; Garmin canonical/default)

R04 release closeout: [R04_RELEASE_CLOSEOUT.md](R04_RELEASE_CLOSEOUT.md).
R05 release closeout: [R05_RELEASE_CLOSEOUT.md](R05_RELEASE_CLOSEOUT.md).

**Current planning focus: post-#119 bounded product work (#127 Period Brief local UI v1).** #98 / #99 are completed maintenance, not residual backlog. Parallel CI/reliability track #123–#126 is separate engineering work, not the next health-product release.

R05 closed on canonical `main @ 46e59327…` with exact-main CI `35130647037` SUCCESS (#106). #119 completed on `main @ 2c19ca968f84efb5e69c1a859ce6016939e617ca` (exact-main CI `35139999279` SUCCESS). #105 remains deferred/NOT_ELIGIBLE. `account_wearables_sleep_observations_v1` stays exploratory/uncertain-only.

## R00 — Final architecture (complete)

Delivered:

- product boundary and source-priority decisions;
- local-first Python/FastAPI/SQLite architecture;
- provenance/canonical/coverage rules;
- donor/license audit and exact-source discipline;
- first implementation contracts.

## R01 — Weight & Body Composition (released)

Delivered the reusable core and first useful product slice:

- local runtime and migrations;
- Xiaomi historical screenshot/photo import with confirmation and provenance;
- openScale/openScale-sync live contract;
- canonical selection and sparse coverage;
- deterministic weight/body-composition analytics;
- local dashboard and safe profile backup/restore.

See [R01 Release Closeout](R01_RELEASE_CLOSEOUT.md).

## R02 — Garmin ingestion and backfill (released)

Delivered:

- protected owner-assisted Garmin session reuse;
- reviewed capability, normalization and persistence contracts;
- typed Garmin current/source/observation records;
- incremental sync and trailing reconciliation;
- bounded resumable historical backfill;
- explicit coverage/checkpoint namespaces;
- exact completed-rerun idempotency and privacy-safe owner diagnostics.

The owner release gate exposed real-provider convergence defects that synthetic CI had not proven; focused repairs were integrated before release.

See [R02 Release Closeout](R02_RELEASE_CLOSEOUT.md).

## R03 — Garmin analytics and activity comparison (released)

Delivered the first deterministic owner analytics layer over R02 evidence:

- reviewed analytic metric/time/coverage contract and immutable evidence manifests;
- scalar personal baselines, quantiles, robust trend and deviation summaries;
- deterministic activity/cycling session comparison;
- bounded lagged cross-metric association primitives with explicit lag direction and no causal claims;
- read-only query service and owner Garmin dashboard;
- provider-native score wording without inventing a Health-Check readiness/recovery score;
- populated-database migration hardening before owner UAT.

R03 remains Garmin-only. Cross-source comparison belongs to R05.

## R04 — Google Health ingestion (released)

Released from `integration/r04-google-health` through PR #114.

Delivered:

- Google Health API v4 only; no new legacy Fitbit Web API path;
- Web Application OAuth with fixed registered loopback callback;
- exactly the accepted read scopes for sleep and health metrics/measurements;
- Windows user-scoped protected Google client/token/session state outside Git;
- explicit `google_*` source/raw/typed persistence and normalization;
- bounded incremental sync, historical backfill and explicit refresh/reconciliation;
- coverage, checkpoints, request budgets, resumability and exact completed-window skip semantics;
- privacy-safe structural diagnostics and fail-closed provider-shape handling;
- owner-live OAuth/capability, sync/backfill/refresh and populated-DB integrity acceptance.

A live terminal HTTP-200 list response with omitted empty repeated fields exposed a provider serialization variant. Focused repair #110 accepts only the proven terminal missing-collection/no-token LIST/RECONCILE case as empty; null/non-array/malformed shapes remain fail-closed.

Release lineage:

- candidate `406f4044ffb0d010c64a8635d402016ae916fc5a`
- release merge `bb5776e98d259cb6256c95bd49d400dc1238af61`
- post-main CI `34768452960` SUCCESS
- tracker #80 closed completed

See [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md).

## R05 — Garmin / Google wearable agreement and canonical sleep (released)

Release status: **released to canonical `main`** (#106 closeout; design #97).

Core model:

```text
source evidence
   -> pairing / eligibility
   -> comparable metric projection
   -> immutable versioned agreement run
   -> optional versioned canonical-source rule
```

Key rules:

- sleep belongs to local wake date;
- one main overnight session per source/date; naps excluded from overnight pairing;
- ambiguous multiple-main sessions fail closed;
- `fitbit_device` cohort requires explicit persisted Fitbit/device metadata;
- `google_wearables_family` is broader family evidence and remains exploratory only;
- manual Google-edited evidence may be exploratory but does not count toward the stronger canonical gate;
- per-metric difference is `google - garmin`;
- compare duration/timing/time-in-bed/stages/WASO where semantics are actually compatible;
- RHR/SpO2 may be agreement-only; HRV/respiration are outside R05 v1 unless the accepted issue explicitly changes scope;
- provider scores are display-only and are never treated as equivalent measurements;
- agreement statistics include N, bias, MAE, RMSE, Bland–Altman limits and robust summaries; association is secondary;
- first exploratory report: 14 paired nights;
- provisional canonical-source decision: 42 valid `device_pair` nights across at least six weeks plus coverage/stability checks;
- canonical default remains Garmin until a reviewed versioned per-metric rule changes it; there is no automatic switch from N/correlation/coverage alone.

Implementation graph:

- **#100** — source eligibility / night pairing
- **#101** — comparable sleep projection
- **#102** — immutable/versioned agreement-run persistence and replay
- **#103** — agreement statistics + 14/42 gates
- **#104** — report / source overlays
- **#105** — versioned canonical-source rule, only after sufficient live `device_pair` evidence
- **#106** — owner UAT / closeout

R05 closed with an exploratory agreement report; live evidence was insufficient to change the canonical source. Garmin remains canonical/default; #105 deferred/NOT_ELIGIBLE.

See [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md).

## Post-R05 bounded product focus

- **#119** — deterministic period brief v1 — **completed** on `main @ 2c19ca96…` (CI `35139999279` SUCCESS): weight/sleep/activity/data-quality evidence packet, stable result hash, thin API/text/CLI rendering; accepted R05 sleep-report reuse and full activity inventory repairs; no LLM/Telegram delivery in v1.
- **#127** — Period Brief local UI v1 — **current bounded product focus** (presentation over the accepted #119 contract; no new analytics; no invented release number for this slice).

Completed maintenance (not residual backlog): #98 Garmin dependency upgrade; #99 Google auth/sync test hardening.

Separate engineering track (not next health-product release): #123–#126 CI/reliability.

## R06 — Context, Telegram, and read-only AI tools

- low-friction free-text event/exposure capture;
- typed read-only analytic tools that return compact evidence packets;
- conversational investigation over deterministic results;
- no unrestricted SQL or raw-series mathematics by the LLM.

## R07 — Saved reports and delivery

- one deterministic report/evidence model for weekly, month-end and annual reviews;
- dashboard archive;
- Telegram/email renderers and delivery audit/retry.

## R08 — Deeper personal analytics and experiments

- event-aligned / matched-control context analysis;
- lagged comparisons and effect sizes with coverage gates;
- structured n-of-1 experiments;
- consider a transparent Recovery Score only if the accumulated data demonstrates a real unmet need.

## R09 — Laboratory, medication, supplement and document data

- original document provenance outside Git;
- confirmed structured analytes/units/reference ranges;
- medication/supplement exposure timelines;
- longitudinal lab + wearable + body-composition context without causal overclaiming.

## R10 — Optional advanced work

- richer timezone/travel semantics when real data requires it;
- additional providers/mobile app only for demonstrated needs;
- secure remote access / additional notification channels;
- optional Obsidian or food-diary summary integration.

## Release gates that always apply

- no real personal health data, screenshots, tokens, secrets or databases in Git/CI;
- every ingestion path is bounded, idempotent and coverage-aware;
- source values survive canonical selection and reprocessing;
- derived values name algorithm/version and input provenance;
- missing/null/zero/unavailable/unknown remain distinct;
- source/device identity claims require explicit evidence;
- new donor code requires license review at the exact reused source version;
- owner UAT is required where private runtime/provider behavior is part of release truth;
- `main` is the only canonical release source.