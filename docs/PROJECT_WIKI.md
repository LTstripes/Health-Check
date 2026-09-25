# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in their release-specific documents and GitHub issues.

## Current canonical state

- Canonical Git branch: `main`
- Current accepted product checkpoint before this documentation refresh: `main @ 9a16ac943dd50a448342ea3b494bf8ccd043997b`
- Exact-main CI: `36018343743` — SUCCESS (`1050 exact nodeids`, Windows smoke PASS)
- Re-read current `main` from GitHub before launch/integration; documentation SHAs are handoff evidence, not permanent architecture truth.
- Latest numbered major release: **R05 — Garmin / Google wearable sleep agreement**.
- Post-R05 Stable Owner Runtime, deterministic Period Brief closeout, Context capture v0 and Garmin Training/Recovery are now canonical and completed.
- Canonical owner data profile: `D:\Garmin\HealthCheck-Stable`; candidate UAT uses disposable verified backup/restore clones, never Stable itself.
- Parent #160 Garmin Training analytics is CLOSED complete through discovery, persistence, normal refresh integration and owner presentation.
- Next bounded data-quality track: **#147 source freshness**, after explicit v1 production policy freeze.
- Deferred presentation work: #172 Period Brief UX follow-up and #189 whole-product Owner UI redesign.
- Current repository visibility is **public**; this does not relax the hard no-private-data-in-Git rule. #167 tracks historical metadata/privacy remediation.
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
- read-only owner Garmin dashboard;
- persist Garmin-native Training Status, daily/chronic load, ACWR, Load Focus and Training Readiness/Recovery evidence with truthful chronology/provenance;
- keep Garmin Training current through the normal one-command Owner refresh;
- show a compact Training & recovery owner section with recent activity Training Effect/load.

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

The accepted Stable-runtime work is reconciled to canonical main and defines the normal long-lived owner operating model:

- one persistent private profile for Weight, Garmin, Google and exploratory agreement evidence;
- supported large-profile backup → verify → restore into disposable clones;
- bounded one-command normal Garmin + Garmin Training + Google owner refresh;
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

Representative remote feedback improved from about **5m02s** to about **2m48s** with the Windows gate included — roughly **44% less wall time** while coverage became stronger. The current #187 exact-main gate reported `1050 exact nodeids reconciled across all mandatory jobs` and `WINDOWS_SMOKE_EVIDENCE: PASS`.

Do not continue CI optimization just to shave seconds. Reopen performance work only if a new measured material bottleneck appears.

### Required-check enforcement limitation

#126 remains an explicit **OWNER DECISION / repository-settings** item. The repository is currently public, so the old private-repository capability statement is historical and must be re-read before any protection change. No settings change is implied by product work.

Until that changes, the manual Integrator gate is mandatory:

- exact target SHA must have final `checks: SUCCESS` before advancing integration or `main`;
- constituent green jobs alone are insufficient;
- only the Integrator advances shared/canonical refs after ACCEPT;
- force-push/deletion of integration/canonical history is process-prohibited.

## Current work

### 1. Source freshness — #147

The old repository-reconciliation and Period Brief closeout queues are finished. The next bounded product track is #147.

Research already established that v1 can be a derived read model without schema change, but implementation must not invent production cadence/thresholds. The Integrator must first freeze the policy table.

Accepted state vocabulary:

`fresh | quiet | stale | unavailable | unknown | not_requested`

Key distinctions:

- daily automatically expected wearable streams use explicit due/grace policy;
- event-driven activities use proven inventory coverage rather than activity age;
- voluntary weight age is non-alert by default;
- refresh outcome, coverage and actual evidence age remain separate facts;
- unknown/insufficient chronology never becomes healthy.

### 2. Separate open tracks

- #153 — Xiaomi S400/openScale live E2E (Owner hardware gate);
- #148 — off-site portable backup / disaster recovery;
- #167 — privacy/history remediation;
- #172 — Period Brief UX follow-up;
- #189 — deferred whole-product Owner UI redesign;
- #126 — repository protection/Owner decision;
- #105 — deferred/NOT_ELIGIBLE canonical sleep rule.

### Completed post-R05 / operational work

#119, #127/#129/#133/#146, #132/#134/#136/#138/#139/#140/#141/#158/#150/#154/#156, #177, #175/#180/#183/#187/#160, #98/#99 and #123–#125 are completed.

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
