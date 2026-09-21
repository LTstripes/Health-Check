# Health-Check Roadmap

The roadmap is organized as usable vertical releases. Each release must work locally on Windows, preserve source evidence, and remain reproducible without live provider access in CI.

Future ideas that are not committed to a release live in [Backlog Ideas](BACKLOG_IDEAS.md).

## Current state

Released to canonical `main`: R01–R05 plus #119 deterministic period brief v1.

Pre-closeout canonical checkpoint used for divergence analysis: `main @ 6f21eeacf80491f73bcf9c5b5411eba1922dd1a4` with exact-main CI `35240124890` SUCCESS. Re-read current `main` from GitHub before launch/integration.

Post-R05 Stable Owner Runtime work is **accepted/live-proven but not yet reconciled to canonical main**:

- owner profile: `D:\Garmin\HealthCheck-Stable`;
- accepted code line: `integration/stable-owner-runtime @ 0b05a80749e3ef0d2fa736778baa49cc23f18a61`;
- exact integration CI: `35581607069` SUCCESS;
- #132 closed completed.

Period Brief presentation line: `integration/period-brief-ui-v1 @ a1d4e4c68674305b78ad3acee8140e96ba5a2e92`; #131 is integrated/closed.

**Immediate sequencing:** reconcile the accepted Stable-runtime line with current main, then complete #146 correctness → #133 presentation hierarchy → #129 Owner UAT/closeout (#127).

See [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md), [Stable Owner Runtime Closeout](STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md), and [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md).

#105 remains deferred/NOT_ELIGIBLE. #126 remains an administrative capability blocker, not product work.

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

## Post-R05 / #119 — deterministic period brief v1 (completed)

#119 delivered:

- deterministic weight/sleep/activity/data-quality evidence packet;
- stable result hash and reproducible input/provenance contract;
- thin API/text/CLI rendering;
- accepted direct R05 sleep-report reuse;
- full bounded activity inventory semantics without display-thinning corrupting analytical counts;
- honest missing/unavailable/confirmed-empty distinctions.

No new health score and no LLM/Telegram delivery were introduced.

## Post-R05 Stable Owner Runtime — accepted/live-proven

The long-lived owner operating model is established: one persistent private cross-domain profile at `D:\Garmin\HealthCheck-Stable`, supported backup/restore into disposable UAT clones, reproducible exploratory R05 agreement, bounded provider refresh, stabilized Google identity and supported stale SyncRun recovery.

The code for this operational slice remains on the accepted Stable integration line until repository reconciliation with current main is completed.

## Current owner-facing product work

### Repository reconciliation gate

Re-read current main, Stable integration and Period Brief integration; reconstruct/merge accepted deltas deliberately and rerun exact-SHA gates.

### Period Brief correctness, UI and UAT

- **#146** — correct the Period Brief producer/consumer seam and effective-window/activity-emptiness truthfulness.
- **#133** — compact owner-facing source labels, summary hierarchy and deterministic deduplication.
- **#129** — Owner-only UAT/closeout using a disposable backup-restored Stable clone.
- **#127** — closes with successful Period Brief UI/UAT.

### Separate future owner-value backlog

- **#147** — metric-aware source freshness/silent-source signal.
- **#148** — off-site portable backup and disaster-recovery rehearsal.
- **#153** — real Xiaomi S400/openScale → Stable E2E verification.
- **#160** — Garmin-native training/performance discovery → bounded persistence/presentation where proven.

## Engineering maintenance — CI feedback/reliability closeout

#123–#125 are complete and integrated.

Outcome:

- pre-parallel accepted remote reference: ~`5m02s`;
- final Windows-inclusive integration: ~`2m48s` (`35235216797`);
- roughly **44% lower wall time**;
- final `checks` proves exact Linux nodeid reconciliation and focused Windows evidence;
- native Windows DPAPI, real PowerShell startup, loopback UI/ingest separation and cleanup are now exercised on a hosted Windows runner.

The performance campaign is stopped by design. No xdist/cache/fixture tuning is planned absent a new material measured problem.

#126 remains **BLOCKED / OWNER DECISION REQUIRED** because private-repository server-side branch protection/required-check enforcement is unavailable under the current GitHub capability. The repository remains private. Until capability changes, exact-SHA `checks: SUCCESS` is a mandatory manual Integrator promotion gate.

See [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md).

## R06 — Context, Telegram, and read-only AI tools

- low-friction free-text event/exposure capture;
- typed read-only analytic tools that return compact evidence packets;
- conversational investigation over deterministic results;
- no unrestricted SQL or raw-series mathematics by the LLM.

R06 remains future direction, not an automatic next launch while current Period Brief/Stable Runtime owner work is still being closed out.

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
- `main` is the only canonical release source;
- stabilized candidate/integration/main promotion uses the accepted final `checks` gate on the exact SHA; while #126 is blocked, this is enforced by Integrator process rather than GitHub branch protection.