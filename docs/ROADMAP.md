# Health-Check Roadmap

The roadmap is organized as usable vertical releases. Each release must work locally on Windows, preserve source evidence, and remain reproducible without live provider access in CI.

Future ideas that are not committed to a release live in [Backlog Ideas](BACKLOG_IDEAS.md).


## Current state

Released to canonical `main`: R01–R05 plus deterministic Period Brief, durable Owner Runtime, Context Capture v0, Garmin Training/Recovery, source freshness, the Owner screenshot workflow and the completed reliability/correction slice.

Current checkpoint: `main @ ac1df6dd5bdcfdc57c56a9b531e89a108a658d2b`; exact-main CI `36818997839` SUCCESS, including Windows smoke and final `checks`. Re-read live GitHub main/CI before launch/integration.

Latest completed work:
- #217/#219/#221 screenshot -> repo skill -> strict Owner-assisted extraction -> R01 pipeline -> Stable;
- #203 Windows limited-encoding Period Brief stdout;
- #226 screenshot algorithm/provenance guard;
- #227 coherent SQLite/ORM compound reads;
- #233 collision-safe Garmin Training privacy test oracle;
- #181 Windows cleanup + full-rerun-only CI provenance, including post-merge transient-WMI follow-up PR #237;
- #229 reviewable changed-sidecar corrections with signed-zero-stable replay identity;
- #147/#191/#193 source freshness and #199/#206/#207/#212 Google HR performance/reliability.

The next sequence is operational proof, then durability. UI remains deferred unless explicitly reprioritized. This table is a status/priority map, **not an automatic Worker queue**.

## Current backlog — 2026-10-01

Eleven open issues, excluding pull requests:

| Issue | Current state | Next bounded action |
| --- | --- | --- |
| #214 | Phase A PASS; Scheduler configured; manual PASS | Prove one untouched automatic daily/logon run with final JSON, task result and honest freshness |
| #215 | Owner input required | One real private context note plus supported read-back; no fabricated text or mandatory daily diary |
| #148 | Durability/security work not complete | Freeze bounded protection/publication/retention and recovery contract, then implementation/review and separate Owner rehearsal |
| #228 | Phase 1 research accepted; implementation parked | Wait for explicit trustworthy event-identity/Owner-decision contract; no date/value/fuzzy auto-merge |
| #153 | Optional compatibility | Numeric `userId` from installed openScale-sync versus current string receiver; not a Weight prerequisite |
| #172 | Deferred UX follow-up | Coordinate with #189, do not independently duplicate UI redesign |
| #189 | Deferred whole-product UI umbrella | Revisit after operational readiness/durability priorities or explicit Owner reprioritization |
| #167 | Deferred by Owner decision | No history rewrite/visibility change without a new explicit decision and freeze |
| #126 | Owner/capability decision | Recheck current capability before any settings change; preserve manual exact-SHA gate |
| #105 | NOT_ELIGIBLE | No canonical sleep switch until the existing device-pair gate is met |
| #210 | Ongoing evidence tracker | Record real model outcomes and Owner-confirmed identities; not a product coding task |

### Operational disposition

#214 historical audit did not justify a broad Garmin or all-stream Google rebuild. Google sample-HR historical coverage had an identified gap; the Owner chose **high-frequency Google `heart_rate` OFF by default** in the local Ops runner. Existing history stays intact. The gap is intentionally not backfilled while disabled.

Other Google streams, wearables sleep, Garmin and Garmin Training remain enabled with the existing reconciliation horizon. The last accepted manual selected-stream run succeeded in 35m32.734s; one prior automatic attempt was interrupted and does not satisfy scheduled-run acceptance.

Weight is operational through screenshots. #229 now adds explicit reviewable correction/replay semantics to that released path. #153/openScale remains optional, not a hidden prerequisite for #214/#215 or later UI. #228's accepted research does not itself add cross-image semantic dedup.

See [Current Execution History](EXECUTION_HISTORY_CURRENT.md), [Owner Refresh](OWNER_REFRESH.md), [Owner Screenshot Import](OWNER_WEIGHT_SCREENSHOT_IMPORT.md) and [Model Journal](MODEL_BENCHMARK.md).

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

#203 later repaired limited-encoding CLI output. #227 establishes coherent compound read snapshots without changing packet mathematics. No new health score and no LLM/Telegram delivery were introduced.

## Post-R05 Stable Owner Runtime — completed foundation

The long-lived owner operating model is established and reconciled to canonical `main`: one persistent private cross-domain profile at `D:\Garmin\HealthCheck-Stable`, supported backup/restore into disposable UAT clones, reproducible exploratory R05 agreement, bounded provider refresh, stabilized Google identity and supported stale SyncRun recovery.

Normal `owner-refresh` composes normal Garmin sync, bounded Garmin Training sync, selected normal Google streams and fixed wearables-sleep reconciliation under one profile-scoped operation boundary. #214 owns actual unattended operational proof, separately from this completed foundation.

## Post-R05 Garmin Training & Recovery — completed

Parent #160 closed after accepted phases:

- #175 — bounded privacy-safe Owner-live discovery established usable Garmin-native status/load/readiness/activity surfaces and chronology/provenance limits;
- #180 — typed additive persistence for Training Status/load/ACWR, Load Focus and Readiness/Recovery with live replay/idempotency proof;
- #183 — normal Owner refresh includes bounded Training sync using the same Garmin auth/client;
- #187 — read-only Training & recovery owner section, accepted by semantic review and Owner UAT.

No custom Health-Check readiness/training score, medical/coaching claim, VO2 guessing or producer attribution was introduced. The page remains intentionally technical until #189.

## Current owner-facing product work

### Source freshness / data-quality interpretation — completed

#147/#191/#193 delivered the versioned provider-call-free derived model over persisted facts. Owner refresh and Period Brief reuse it. Daily wearable streams, event-driven activities, voluntary Weight and optional/unsupported evidence remain distinct. #214 now proves its routine operational use; it does not reopen freshness formulas or thresholds.

### Hardware/private owner gates

- **#153** — optional openScale compatibility, not required for the accepted screenshot route.
- **#215** — first actual private Context note/read-back.
- **#148** — protected off-site backup/disaster-recovery rehearsal, with design/implementation acceptance before live use.

### Deferred product presentation

- **#172** — Period Brief-specific UX follow-up.
- **#189** — whole-product Owner UI redesign umbrella.

## Engineering maintenance — CI feedback/reliability closeout

#123–#125 are complete and integrated.

Historical measured outcome:

- pre-parallel accepted remote reference: ~`5m02s`;
- final Windows-inclusive integration: ~`2m48s` (`35235216797`);
- roughly **44% lower wall time**;
- final `checks` proves exact Linux nodeid reconciliation and focused Windows evidence;
- native Windows DPAPI, PowerShell startup, loopback UI/ingest separation and cleanup are exercised on a hosted Windows runner.

The performance campaign remains stopped absent a new material measured bottleneck. #181 is now complete: Windows cleanup preserves fail-closed ownership/CreationTime evidence, exact exit-255 transcript handling and full-rerun-only provenance; its post-merge WMI transient was retained as an escape and repaired before final green main.

#126 remains an explicit Owner/repository-settings decision. The repository is currently public; re-evaluate capability before settings changes. Exact-SHA `checks: SUCCESS` remains mandatory regardless of server enforcement.

See [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md).

## R06 — Context, Telegram, and read-only AI tools

- low-friction free-text event/exposure capture;
- typed read-only analytic tools that return compact evidence packets;
- conversational investigation over deterministic results;
- no unrestricted SQL or raw-series mathematics by the LLM.

Context capture v0 is accepted, but real Stable adoption (#215), Telegram and bounded AI tooling are separate stages. No new AI/Telegram release is launched by this documentation refresh.

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
- candidate/integration/main promotion uses the accepted final `checks` gate on the exact SHA; while #126 is blocked this is enforced by Integrator process.
